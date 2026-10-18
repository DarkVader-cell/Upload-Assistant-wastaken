# HDB screenshot rehosting

Normal HDB uploads use the existing capture-validated main screenshots. Older
workspaces without a screenshot manifest retain the legacy typed-directory PNG
lookup. If local screenshots are absent but full-size `raw_url` entries exist in
the release's hosted image list, UA downloads and verifies those images before
rehosting them to HDB. It never substitutes a gallery page or a thumbnail as a
full-size source.

The image API needs `TRACKERS.HDBITS.username` and `passkey`. Browser cookies
authenticate torrent submission, **not** `img.hdbits.org/upload_api.php`.

HTTP 200 alone is not treated as a successful image upload: UA checks the
returned HDB BBCode and expected image count. Rejected/incomplete bulk requests
are retried as individual images. Redirects during recovery are revalidated,
downloads are bounded to 32 MiB/image, and decoded images are checked before
being sent to the image API.

## Non-blocking warning policy

At the operator's request, screenshot failures do **not** abort a normal torrent
upload. UA falls back to existing hosted screenshot links when available and
shows `HDBITS SCREENSHOT WARNING` in the console and upload result. Details are
also retained in `tmp/<release>/HDB_SCREENSHOTS_WARNING.txt` and tracker status.
If no usable links remain, the warning explicitly asks you to add screenshots
manually on HDBits. Check the final site description; external fallback hosts
may not render the same as HDB-hosted images.

A later successful rehosting attempt clears the prior screenshot warning.
This does not edit releases already uploaded; existing imageless releases still
need their descriptions repaired manually. Offer-only generation retains its
image validation safeguards and does not submit torrents.
