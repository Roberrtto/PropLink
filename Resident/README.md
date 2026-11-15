# PropLink Resident App

Flutter app for residents: sign in, view bills, pay via M-Pesa, request services and maintenance.

## Run
1. Start the backend on port 8000 (see the root README).
2. `flutter pub get`
3. Android emulator: `flutter run` (the app reaches your PC at 10.0.2.2:8000).
4. Real phone over USB:
   adb reverse tcp:8000 tcp:8000
   flutter run --dart-define=API_URL=http://localhost:8000

## Windows note
If the project is on a different drive from the Pub cache (e.g. project on R:, cache on C:),
`android/gradle.properties` must contain `kotlin.incremental=false`, or the Kotlin build fails with
"Could not close incremental caches".