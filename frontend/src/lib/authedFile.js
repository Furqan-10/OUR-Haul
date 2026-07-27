import { useEffect, useState } from "react";
import api from "./api";
import driverApi from "./driverApi";
import { toast } from "sonner";

/**
 * Fetching protected files without putting the session token in the URL.
 *
 * `<img src>` and `<a href>` cannot send an Authorization header, so the app
 * used to append `?auth=<session token>` to the file URL. That leaks a live
 * credential into places built to be retained and shared: web server and proxy
 * access logs, browser history, and the Referer header sent to any third-party
 * resource on a page opened from that tab.
 *
 * These helpers fetch the file with XHR (token in the header, where it belongs)
 * and hand back an object URL, which is local to the document and carries no
 * credential at all.
 */

async function fetchObjectUrl(client, path) {
  const res = await client.get(path, { responseType: "blob" });
  const type = res.headers?.["content-type"] || "application/octet-stream";
  return URL.createObjectURL(new Blob([res.data], { type }));
}

/**
 * Object URL for a protected file, for use as an `<img src>`.
 * Revoked on unmount so blobs are not retained.
 */
export function useAuthedFile(fileId, { driver = false } = {}) {
  const [url, setUrl] = useState(null);

  useEffect(() => {
    if (!fileId) return undefined;
    let revoked = false;
    let objectUrl = null;
    const client = driver ? driverApi : api;
    const path = driver ? `/driver/files/${fileId}` : `/files/${fileId}`;

    fetchObjectUrl(client, path)
      .then((u) => {
        // The component may have unmounted while the request was in flight.
        if (revoked) URL.revokeObjectURL(u);
        else {
          objectUrl = u;
          setUrl(u);
        }
      })
      .catch(() => setUrl(null));

    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [fileId, driver]);

  return url;
}

/** Open a protected file in a new tab. Use from an onClick, not an href. */
export async function openAuthedFile(fileId, { driver = false } = {}) {
  const client = driver ? driverApi : api;
  const path = driver ? `/driver/files/${fileId}` : `/files/${fileId}`;
  try {
    const url = await fetchObjectUrl(client, path);
    const win = window.open(url, "_blank", "noopener,noreferrer");
    if (!win) toast.error("Allow pop-ups to view this file");
    // Give the new tab time to load before releasing the blob.
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch {
    toast.error("Could not open that file");
  }
}

/** Thumbnail that resolves its own object URL. */
export function AuthedImage({ fileId, alt = "", className = "", driver = false, ...rest }) {
  const url = useAuthedFile(fileId, { driver });
  if (!url) return <div className={`bg-slate-100 animate-pulse ${className}`} aria-label={alt} />;
  return <img src={url} alt={alt} className={className} {...rest} />;
}
