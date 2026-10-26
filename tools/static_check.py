"""
Two checks that catch mistakes a test would hit straight away, without starting the app:

  1. names:   a function uses a name that was never imported or defined (a typo, or a
              forgotten import), or a name is used before a local import below it
  2. fields:  code reads or filters on a database field that the model does not have
              (Model.some_field, Model.query.filter_by(some_field=...), Model(some_field=...))

  3. imports: every "from app.x import name" points at a name that really exists in app/x.py

Run from the project root:   python tools/static_check.py
"""
import ast
import builtins
import os
import symtable
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
problems = []

SKIP = ("venv", "__pycache__", ".git", "node_modules", "mobile-wrapper", "tools")


def py_files():
    for base, _, files in os.walk(ROOT):
        if any(p in base.split(os.sep) for p in SKIP):
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


# ---------------------------------------------------------------- 1. names
def check_names(path):
    src = open(path, encoding="utf-8").read()
    table = symtable.symtable(src, path, "exec")
    module_names = {s.get_name() for s in table.get_symbols() if s.is_assigned() or s.is_imported() or s.is_namespace()}
    allowed = module_names | set(dir(builtins)) | {"__file__", "__name__", "__doc__"}

    def walk(t, scope):
        for sym in t.get_symbols():
            name = sym.get_name()
            if sym.is_referenced() and sym.is_global() and name not in allowed:
                problems.append(f"{os.path.relpath(path, ROOT)}: '{name}' used in {scope or 'module'} but never defined or imported")
            # a name that is both assigned locally (e.g. a later import) and read earlier is a crash
            if sym.is_local() and sym.is_referenced() and sym.is_imported() and t.get_type() == "function":
                pass
        for child in t.get_children():
            walk(child, f"{scope}.{child.get_name()}" if scope else child.get_name())

    walk(table, "")

    # "used before assignment" for local imports/assignments inside a function
    tree = ast.parse(src)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first_use, first_bind = {}, {}
        local_scopes = set()            # loop variables inside comprehensions and lambdas live in their own scope
        for node in ast.walk(fn):
            if isinstance(node, ast.comprehension):
                local_scopes |= {n.id for n in ast.walk(node.target) if isinstance(n, ast.Name)}
            elif isinstance(node, ast.Lambda):
                local_scopes |= {a.arg for a in node.args.args}
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                first_use.setdefault(node.id, node.lineno)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                first_bind.setdefault(node.id, node.lineno)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    first_bind.setdefault((a.asname or a.name).split(".")[0], node.lineno)
        args = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        for name, bind_line in first_bind.items():
            use_line = first_use.get(name)
            if use_line and use_line < bind_line and name not in args and name not in local_scopes \
                    and name not in module_level_names(tree):
                problems.append(f"{os.path.relpath(path, ROOT)}:{use_line}: '{name}' is used before it is assigned in {fn.name}()")


def module_level_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


# ---------------------------------------------------------------- 2. model fields
def model_fields():
    tree = ast.parse(open(os.path.join(ROOT, "app", "models.py"), encoding="utf-8").read())
    models = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            attrs = {"query", "metadata", "id"}
            bases = {getattr(b, "attr", getattr(b, "id", "")) for b in node.bases}
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            attrs.add(t.id)
                elif isinstance(item, (ast.FunctionDef,)):
                    attrs.add(item.name)
            # backrefs defined as back_populates/backref names on the other side are real attributes too
            for sub in ast.walk(node):
                if isinstance(sub, ast.keyword) and sub.arg == "backref" and isinstance(sub.value, ast.Constant):
                    attrs.add(sub.value.value)
            models[node.name] = {"attrs": attrs, "is_model": "Model" in bases}
    # add back_populates targets onto the matching classes
    return models


def check_fields(path, models):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    rel = os.path.relpath(path, ROOT)
    real = {n for n, m in models.items() if m["is_model"]}
    imported = module_level_names(tree)
    for node in ast.walk(tree):
        # Model.attr
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in real \
                and node.value.id in imported_models(tree, real):
            if node.attr not in models[node.value.id]["attrs"] and not node.attr.startswith("__"):
                problems.append(f"{rel}:{node.lineno}: {node.value.id}.{node.attr} is not a field of {node.value.id}")
        # Model.query.filter_by(field=...) and Model(field=...)
        if isinstance(node, ast.Call):
            fn = node.func
            model = None
            if isinstance(fn, ast.Attribute) and fn.attr == "filter_by":
                v = fn.value
                if isinstance(v, ast.Attribute) and v.attr == "query" and isinstance(v.value, ast.Name):
                    model = v.value.id
            elif isinstance(fn, ast.Name) and fn.id in real:
                model = fn.id
            if model in real and model in imported_models(tree, real):
                for kw in node.keywords:
                    if kw.arg and kw.arg not in models[model]["attrs"]:
                        problems.append(f"{rel}:{node.lineno}: {model}({kw.arg}=...) but {model} has no field '{kw.arg}'")


def imported_models(tree, real):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.models":
            for a in node.names:
                if a.name in real:
                    found.add(a.asname or a.name)
    return found


# ---------------------------------------------------------------- 3. imports resolve
def defined_in(module_path):
    tree = ast.parse(open(module_path, encoding="utf-8").read())
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, (ast.If, ast.Try)):          # definitions inside if/try at module level
            for sub in ast.walk(node):
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)):
                    names.add(sub.name)
                elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                    names.add(sub.id)
    return names


def module_file(dotted):
    base = os.path.join(ROOT, *dotted.split("."))
    if os.path.isfile(base + ".py"):
        return base + ".py"
    if os.path.isfile(os.path.join(base, "__init__.py")):
        return os.path.join(base, "__init__.py")
    return None


def check_imports(path):
    tree = ast.parse(open(path, encoding="utf-8").read())
    rel = os.path.relpath(path, ROOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and (node.module == "app" or node.module.startswith("app.")):
            target = module_file(node.module)
            if target is None:
                problems.append(f"{rel}:{node.lineno}: imports from {node.module}, which does not exist")
                continue
            have = defined_in(target)
            for a in node.names:
                if a.name == "*" or a.name in have:
                    continue
                if module_file(f"{node.module}.{a.name}"):          # importing a submodule
                    continue
                problems.append(f"{rel}:{node.lineno}: cannot import '{a.name}' from {node.module}")


models = model_fields()
# back_populates: attributes created on the other class via relationship(..., back_populates="x") exist on this class too
mtree = ast.parse(open(os.path.join(ROOT, "app", "models.py"), encoding="utf-8").read())
for cls in [n for n in mtree.body if isinstance(n, ast.ClassDef)]:
    for sub in ast.walk(cls):
        if isinstance(sub, ast.keyword) and sub.arg == "back_populates" and isinstance(sub.value, ast.Constant):
            target = None
            call = None
        if isinstance(sub, ast.Call) and getattr(sub.func, "attr", "") == "relationship" and sub.args:
            if isinstance(sub.args[0], ast.Constant) and sub.args[0].value in models:
                for kw in sub.keywords:
                    if kw.arg == "back_populates" and isinstance(kw.value, ast.Constant):
                        models[sub.args[0].value]["attrs"].add(kw.value.value)

for path in py_files():
    check_imports(path)
    check_names(path)
    if not path.endswith(os.path.join("app", "models.py")):
        check_fields(path, models)

if problems:
    print(f"{len(problems)} problem(s):")
    for p in sorted(set(problems)):
        print("  ", p)
    sys.exit(1)
print("static_check: no undefined names, no unknown model fields, and every import resolves.")
