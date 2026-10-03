# Campus Swap — Mobile App Wrapper

This folder wraps the live Campus Swap website in a native shell using
[Capacitor](https://capacitorjs.com/), so it can be built into a real
installable Android `.apk`/`.aab` and iOS `.ipa`.

**Important: this is a wrapper, not a rewrite.** The app still needs your
Flask server running somewhere reachable over the internet (Campus Swap
itself was not changed to work this way — it's the same Flask app). The
native shell just opens your deployed site full-screen, with native icons,
splash screen, and app-store packaging.

## Before you start

1. **Deploy Campus Swap somewhere with a real HTTPS domain first**
   (Render, Railway, PythonAnywhere, a VPS, etc.) — `localhost` won't work
   from a phone. iOS in particular refuses plain HTTP, so you need TLS.
2. Open `capacitor.config.json` in this folder and replace
   `REPLACE-WITH-YOUR-DEPLOYED-DOMAIN.example.com` with your real domain.

## What you need installed locally (none of this exists in the sandbox that built this project)

- **Node.js** (v18+) and npm
- **For Android:** [Android Studio](https://developer.android.com/studio)
  with the Android SDK — this gets you the `.apk`/`.aab`
- **For iOS:** a **Mac** with **Xcode** — there is no way around this,
  Apple only allows iOS apps to be built and signed on macOS
- Developer accounts if you want to actually publish:
  [Google Play Console](https://play.google.com/console) (~$25 one-time) and
  [Apple Developer Program](https://developer.apple.com/programs/) (~$99/year)

## Build steps

```bash
cd mobile-wrapper
npm install

# Add the native platform projects (generated, not checked in)
npx cap add android
npx cap add ios      # only works when run on a Mac

# Copy the web assets in and sync native config
npx cap sync

# Open the native IDE to build, sign, and run/export the app
npx cap open android   # opens Android Studio -> Build > Generate Signed Bundle/APK
npx cap open ios       # opens Xcode (Mac only) -> Product > Archive
```

From there, building the signed `.apk`/`.aab` or `.ipa` and submitting to
Google Play / the App Store follows each platform's normal process — this
wrapper just gets you to the starting line.

## Icons and splash screen

The icon set already generated for the web app's PWA
(`app/static/img/icon-192.png`, `icon-512.png`, `icon-512-maskable.png`) is a
good starting point, but Android/iOS expect a larger set of exact sizes.
Use [`@capacitor/assets`](https://github.com/ionic-team/capacitor-assets) to
generate the full platform-specific icon and splash-screen set from a single
source image:

```bash
npm install @capacitor/assets --save-dev
npx capacitor-assets generate --iconBackgroundColor '#157347' --splashBackgroundColor '#eef1f5'
```

## Push notifications, camera access, etc.

If you later want native features Flask can't provide on its own (push
notifications for new messages, native camera access for listing photos),
add the relevant Capacitor plugin (e.g. `@capacitor/push-notifications`,
`@capacitor/camera`) and call it from a small bit of JavaScript in the
Campus Swap templates, guarded behind `if (window.Capacitor)` so the same
templates still work fine in a normal browser.
