# Private PDF Toolkit

A Flutter thin client and self-hosted FastAPI service for private PDF operations. PDF processing runs on the server. The app has no analytics, ads, crash-reporting SDKs, or third-party PDF/conversion/OCR services. Its API client sends requests only to the server URL configured by the user.

## Architecture

```text
┌──────────────────┐       HTTPS        ┌──────────────┐      internal      ┌──────────────┐
│ Flutter mobile   │ ─────────────────> │ Caddy        │ ─────────────────> │ FastAPI      │
│ file picker/UI   │ <───────────────── │ TLS proxy    │ <───────────────── │ API          │
└──────────────────┘   result download  └──────────────┘                    └──────┬───────┘
                                                                                  │
                               ┌──────────────────────────────────────────────────┤
                               │ pikepdf/qpdf · Ghostscript · LibreOffice        │
                               │ PyMuPDF · Pillow/img2pdf · OCRmyPDF/Tesseract   │
                               └──────────────────────────────────────────────────┘
```

## Server deployment on a fresh Ubuntu VPS

1. Point a DNS `A` record for a domain you control to the VPS public IPv4 address. Allow the DNS record to propagate.
2. Install Docker Engine and the Compose plugin using Docker's official Ubuntu instructions: <https://docs.docker.com/engine/install/ubuntu/>. Confirm `docker compose version` works.
3. Clone this repository on the server and enter `pdf-toolkit/server`.
4. Create the private environment file and a strong key:

   ```bash
   cp .env.example .env
   openssl rand -hex 32
   nano .env
   ```

   Set `API_KEY` to the generated random value, set `DOMAIN` to your DNS name, and adjust the limits if needed. Never commit `.env`.
5. Edit `Caddyfile` only if you need a different proxy configuration. Caddy obtains and renews HTTPS certificates automatically when DNS points to the VPS and ports 80/443 are reachable.
6. Start services:

   ```bash
   docker compose up -d --build
   docker compose ps
   docker compose logs --tail=100 api caddy
   ```

7. Verify the public health endpoint:

   ```bash
   curl --fail https://YOUR_DOMAIN/health
   # expected: {"status":"ok"}
   ```

8. Configure the firewall. Make sure you have working SSH access before enabling UFW:

   ```bash
   sudo ufw allow 22/tcp
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp
   sudo ufw enable
   sudo ufw status
   ```

   Do not publish port 8000. It is only exposed to the Compose network. Restrict SSH further to trusted IPs if practical.

### API key rotation

Generate a new key with `openssl rand -hex 32`, replace `API_KEY` in `server/.env`, then run `docker compose up -d --force-recreate api`. Update the key in the mobile app Settings. Requests using the old key will stop working after the service restarts. Avoid sharing the key or storing it in source control.

### Limits and operations

- `MAX_UPLOAD_MB` is per file; `MAX_TOTAL_UPLOAD_MB` is the total uploaded payload per request.
- Caddy limits request bodies to 160 MB. Keep this higher than the API's total limit to allow multipart overhead.
- `MAX_CONCURRENT_JOBS` limits concurrent processing jobs. `RATE_LIMIT_PER_MIN` limits requests per client IP/API-key prefix in the in-memory limiter. Limits reset on restart and are not distributed across replicas.
- The container runs as a non-root user, drops Linux capabilities, uses a read-only root filesystem and mounts `/tmp` as a size-limited tmpfs. Tune `mem_limit` and tmpfs size to your VPS capacity.
- The API requires a valid 24+ character `API_KEY` and intentionally disables OpenAPI docs in production.

## Flutter setup

Install Flutter stable and the Android/iOS toolchains from <https://docs.flutter.dev/get-started/install>. This repository includes the Dart source and package manifest. Generate platform scaffolding once from the `app` directory:

```bash
cd app
flutter create --platforms=android,ios .
flutter pub get
flutter analyze
flutter test
flutter run
```

Set the server URL and API key in Settings. Use the exact public HTTPS URL for a deployed server. HTTP is accepted only for local development hosts (`localhost`, `127.0.0.1`, Android emulator host `10.0.2.2`, and `192.168.x.x` LAN addresses), with a warning. Public deployments should always use HTTPS.

### Android platform configuration

After `flutter create`, apply these settings in `android/app/src/main/AndroidManifest.xml` and `android/app/build.gradle` or `android/app/build.gradle.kts`:

- Add `<uses-permission android:name="android.permission.INTERNET" />` and `<uses-permission android:name="android.permission.CAMERA" />` directly under `<manifest>`.
- On the `<application>` element set `android:allowBackup="false"` and `android:usesCleartextTraffic="false"`.
- Set `minSdk` to 23 or higher.
- If using HTTP for a local development host, Android's cleartext restriction may block it. Prefer local HTTPS; do not weaken cleartext policy for production.

For a release signing key, keep the keystore and passwords outside source control, configure the signing properties in Gradle, then build:

```bash
flutter build apk --release
flutter build appbundle --release
```

The APK/AAB is written under `app/build/app/outputs/`. Do not commit your keystore, `key.properties`, or signing passwords.

### iOS platform configuration

In `ios/Runner/Info.plist`, add `NSCameraUsageDescription` (for example, `Capture images to convert them to PDF`) and `NSPhotoLibraryUsageDescription` (for example, `Choose images to convert them to PDF`). Keep App Transport Security enabled. Build/sign through Xcode with your own Apple developer team. iOS deployment and signing require macOS and Xcode.

## Privacy and data handling

- **What leaves the phone:** only the file(s) selected for the operation, plus the selected operation's parameters, API key, and normal HTTP metadata, sent to the one server URL configured in Settings. The app has no analytics, ad, crash-reporting, telemetry, third-party conversion, OCR, or PDF API SDKs. Connection testing sends a request to that same configured server's `/health` endpoint.
- **What the server logs:** timestamp, endpoint path, HTTP status code, duration, and request `Content-Length` as input size. It does not log filenames, contents, passwords, request bodies, or API keys. Reverse-proxy access logging is disabled.
- **Deletion:** each request uses a UUID-named per-job temporary directory. On successful file responses, FastAPI schedules directory deletion after the response is sent. On errors, the endpoint deletes the directory. Docker's `/tmp` is a tmpfs and is also cleared when the container stops. Temporary result files on the phone are removed after save/share and on the next app start. Saved copies are retained only where the user explicitly saves them. Server administrators should still maintain normal host security and avoid host-level snapshots or backups of temporary data.

## Troubleshooting

- **Connection failed:** check the exact URL (include `https://`), DNS, server health with `curl https://YOUR_DOMAIN/health`, UFW/security-group rules for ports 80/443, and Caddy logs. A self-signed or invalid certificate is intentionally not bypassed by the app.
- **HTTP 413:** reduce the file size or increase `MAX_UPLOAD_MB`/`MAX_TOTAL_UPLOAD_MB`, Caddy's `max_size`, and available memory/tmpfs together. Restart the stack after changing `.env`.
- **LibreOffice timeout:** office conversion is limited to 120 seconds. Check `docker compose logs api`, server RAM, and that the uploaded format is supported. Avoid untrusted macro-enabled documents; conversion is headless but the server should still be isolated.
- **OCR language pack missing:** confirm `tesseract-ocr-eng`, `tesseract-ocr-hin`, `tesseract-ocr-spa`, `tesseract-ocr-fra`, and `tesseract-ocr-deu` are installed in the image. Rebuild with `docker compose up -d --build`.
- **Server reports processing failure:** inspect service health and installed command availability inside the container. Error responses intentionally avoid returning command output or file details.

## API endpoints and curl examples

Replace `YOUR_DOMAIN`, `YOUR_API_KEY`, and local file paths. All endpoints except `/health` require `X-API-Key`. Multipart file field names and form names are case-sensitive.

```bash
# 1. Health (no key)
curl -fsS https://YOUR_DOMAIN/health

# 2. Merge 2-20 PDFs, upload order is merge order
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'files=@one.pdf' -F 'files=@two.pdf' https://YOUR_DOMAIN/merge -o merged.pdf

# 3. Extract selected pages
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'pages=1-3,5,8-10' https://YOUR_DOMAIN/split -o split.pdf

# 4. Split every page into a ZIP
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' https://YOUR_DOMAIN/split-all -o pages.zip

# 5. Reorder and omit pages
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'order=3,1,2,5' https://YOUR_DOMAIN/organize -o organized.pdf

# 6. Rotate all pages or selected pages
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'degrees=90' -F 'pages=1-2' https://YOUR_DOMAIN/rotate -o rotated.pdf

# 7. Add a watermark
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'text=CONFIDENTIAL' -F 'opacity=0.25' -F 'position=diagonal' https://YOUR_DOMAIN/watermark -o watermarked.pdf

# 8. Add page numbers
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'position=bottom-center' -F 'start=1' https://YOUR_DOMAIN/page-numbers -o numbered.pdf

# 9. Password protect (AES-256)
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'password=change-this-password' https://YOUR_DOMAIN/protect -o protected.pdf

# 10. Unlock a PDF
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@protected.pdf' -F 'password=change-this-password' https://YOUR_DOMAIN/unlock -o unlocked.pdf

# 11. Images to PDF (one or more files)
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'files=@photo1.jpg' -F 'files=@photo2.png' https://YOUR_DOMAIN/images-to-pdf -o images.pdf

# 12. PDF pages to image ZIP
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'format=png' -F 'dpi=150' https://YOUR_DOMAIN/pdf-to-images -o rendered.zip

# 13. Compress: low=/printer, medium=/ebook, high=/screen
curl -f -D compression-headers.txt -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' -F 'level=medium' https://YOUR_DOMAIN/compress -o compressed.pdf

# 14. Convert supported office formats
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@document.docx' https://YOUR_DOMAIN/office-to-pdf -o converted.pdf

# 15. OCR language options: eng, hin, spa, fra, deu
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@scan.pdf' -F 'lang=eng' https://YOUR_DOMAIN/ocr -o searchable.pdf

# 16. Read PDF metadata as JSON
curl -f -H 'X-API-Key: YOUR_API_KEY' -F 'file=@input.pdf' https://YOUR_DOMAIN/info
```

## Repository layout

```text
pdf-toolkit/
├── README.md
├── app/                 # Flutter/Dart source, tests and pubspec
└── server/              # FastAPI, tests, Docker and Caddy configuration
```
