"""
Static audit of the Campus Swap project. It reads the code and templates (it does
not start the app) and reports:

  * links: every url_for(...) in templates and Python points at a route that exists,
    and passes the arguments that route needs
  * templates: every extends / include / import points at a file that exists
  * forms: every POST form carries a CSRF token
  * access: which routes need no login, so each can be checked on purpose
  * risky code: debug mode, eval/exec, raw SQL built from text, |safe, verify=False,
    hard-coded secrets, unvalidated redirects
  * browser safety: inline scripts and inline event handlers (they matter for the
    Content-Security-Policy)

Run from the project root:   python tools/audit.py
Exit code is 1 if it finds an ERROR.
"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
TEMPLATES = os.path.join(APP, "templates")
errors, warnings, notes = [], [], []


def py_files():
    for base, _, files in os.walk(ROOT):
        if any(p in base for p in ("venv", "__pycache__", ".git", "node_modules", "mobile-wrapper")):
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


# ---------------------------------------------------------------- routes
routes = {}      # endpoint -> {"rule": str, "args": set, "login": bool, "file": str, "methods": set}
bp_names = {}    # (file, variable) -> blueprint name

for path in py_files():
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            if getattr(fn, "id", "") == "Blueprint" and node.value.args:
                a0 = node.value.args[0]
                if isinstance(a0, ast.Constant):
                    for t in node.targets:
                        if isinstance(t, ast.Name):
                            bp_names[t.id] = a0.value

for path in py_files():
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        rule, bp, endpoint, methods = None, None, None, {"GET"}
        login = admin = False
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "route":
                bp = getattr(dec.func.value, "id", None)
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    rule = dec.args[0].value
                for kw in dec.keywords:
                    if kw.arg == "endpoint" and isinstance(kw.value, ast.Constant):
                        endpoint = kw.value.value
                    if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        methods = {e.value for e in kw.value.elts if isinstance(e, ast.Constant)}
            name = getattr(dec, "id", getattr(dec, "attr", ""))
            if name == "login_required":
                login = True
            if name.endswith("_required") and name != "login_required":
                admin = True
        if rule is None or bp is None:
            continue
        bpname = bp_names.get(bp, bp)
        routes[f"{bpname}.{endpoint or node.name}"] = {
            "rule": rule, "args": set(re.findall(r"<(?:\w+:)?(\w+)>", rule)),
            "login": login or admin, "admin": admin, "file": os.path.relpath(path, ROOT),
            "methods": methods}

# app-level rules registered outside blueprints are not needed by templates; static is built in.

# ---------------------------------------------------------------- templates
URL_FOR = re.compile(r"url_for\(\s*['\"]([\w.]+)['\"]\s*((?:,[^()]*(?:\([^()]*\)[^()]*)*)?)\)")


def check_url_for(source, label):
    for m in URL_FOR.finditer(source):
        ep, rest = m.group(1), m.group(2)
        if ep == "static":
            lit = re.search(r"filename\s*=\s*['\"]([^'\"]+)['\"]", rest)
            if lit and not os.path.exists(os.path.join(APP, "static", lit.group(1))):
                errors.append(f"{label}: static file missing: {lit.group(1)}")
            continue
        if ep not in routes:
            errors.append(f"{label}: url_for('{ep}') but no such route")
            continue
        given = set(re.findall(r"(\w+)\s*=", rest))
        missing = routes[ep]["args"] - given
        if missing:
            errors.append(f"{label}: url_for('{ep}') is missing argument(s) {sorted(missing)}")


tpl_files = []
for base, _, files in os.walk(TEMPLATES):
    for f in files:
        if f.endswith(".html"):
            tpl_files.append(os.path.join(base, f))

inline_scripts = inline_handlers = 0
for path in sorted(tpl_files):
    rel = os.path.relpath(path, ROOT)
    src = open(path, encoding="utf-8").read()
    check_url_for(src, rel)
    for m in re.finditer(r"{%\s*(?:extends|include|import|from)\s+['\"]([^'\"]+)['\"]", src):
        if not os.path.exists(os.path.join(TEMPLATES, m.group(1))):
            errors.append(f"{rel}: template not found: {m.group(1)}")
    for m in re.finditer(r"<form\b[^>]*>(.*?)</form>", src, re.S | re.I):
        tag = re.match(r"<form\b[^>]*>", m.group(0), re.I).group(0)
        if re.search(r"method\s*=\s*['\"]?post", tag, re.I) and "csrf_token" not in m.group(1) \
                and "hidden_tag" not in m.group(1):
            errors.append(f"{rel}: POST form without a CSRF token")
    for m in re.finditer(r"href\s*=\s*['\"](#?|javascript:[^'\"]*)['\"]", src, re.I):
        if m.group(1) in ("", "#") or m.group(1).startswith("javascript"):
            warnings.append(f"{rel}: dead or javascript link: href=\"{m.group(1)}\"")
    for m in re.finditer(r"<script\b([^>]*)>", src, re.I):
        if "src=" not in m.group(1).lower():
            inline_scripts += 1
    inline_handlers += len(re.findall(r"\son(?:click|change|submit|input|load|error|focus|blur|keyup|keydown)\s*=", src, re.I))
    for m in re.finditer(r"\|\s*safe\b", src):
        warnings.append(f"{rel}: uses |safe (output is not escaped)")
    if re.search(r"target\s*=\s*['\"]_blank['\"](?![^>]*noopener)", src, re.I):
        warnings.append(f"{rel}: target=_blank link without rel=noopener")

# ---------------------------------------------------------------- python
for path in py_files():
    rel = os.path.relpath(path, ROOT)
    if rel.startswith("tools") or rel.startswith("tests"):
        continue
    src = open(path, encoding="utf-8").read()
    check_url_for(src, rel)
    for n, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith("#"):
            continue
        if re.search(r"\bapp\.run\([^)]*debug\s*=\s*True", s):
            errors.append(f"{rel}:{n}: app.run(debug=True) exposes the interactive debugger")
        if re.search(r"\b(eval|exec)\(", s):
            errors.append(f"{rel}:{n}: eval/exec")
        if re.search(r"\b(os\.system|subprocess\.|pickle\.loads|yaml\.load\()", s):
            errors.append(f"{rel}:{n}: risky call: {s[:60]}")
        if re.search(r"verify\s*=\s*False", s):
            errors.append(f"{rel}:{n}: TLS verification turned off")
        if re.search(r"\.execute\(\s*f['\"]|\.execute\([^)]*%\s|\.execute\([^)]*\+", s) and "ALTER TABLE" not in s \
                and "CREATE UNIQUE INDEX" not in s:
            warnings.append(f"{rel}:{n}: SQL built from text: {s[:70]}")
        if re.search(r"(secret|password|token|api_key)\w*\s*=\s*['\"][^'\"]{6,}['\"]", s, re.I) \
                and "environ" not in s and "get(" not in s and "generate_password_hash" not in s \
                and "testing-only" not in s:
            warnings.append(f"{rel}:{n}: possible hard-coded secret: {s[:70]}")
        if "render_template_string" in s:
            errors.append(f"{rel}:{n}: render_template_string")
        if re.search(r"redirect\(\s*(?:request\.(?:args|form|values)|next_page|next_url)", s):
            errors.append(f"{rel}:{n}: redirect to a user-supplied address without checking it")

# ---------------------------------------------------------------- access report
public = sorted(e for e, r in routes.items() if not r["login"])
cfg = open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
init_src = open(os.path.join(APP, "__init__.py"), encoding="utf-8").read()
if "dev-secret-key" in cfg and "SECRET_KEY is missing or too weak" not in init_src:
    warnings.append("config.py: a placeholder SECRET_KEY default exists and nothing stops production using it")

print(f"Routes found: {len(routes)}   Templates: {len(tpl_files)}")
print(f"Routes that need no login ({len(public)}):")
for e in public:
    r = routes[e]
    print(f"   {e:42} {','.join(sorted(r['methods'])):9} {r['rule']}")
print(f"\nInline <script> blocks: {inline_scripts}    inline event handlers: {inline_handlers}")
print(f"\nERRORS ({len(errors)})")
for e in errors:
    print("  ERROR  ", e)
print(f"\nWARNINGS ({len(warnings)})")
for w in warnings:
    print("  warn   ", w)
sys.exit(1 if errors else 0)
