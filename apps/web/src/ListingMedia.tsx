import { type ChangeEvent, useEffect, useRef, useState } from "react";

import { api, describeError, uploadFile } from "./api";
import type { components } from "./api-schema";

type Media = components["schemas"]["MediaOut"];
type Upload = {
  key: number;
  file: File;
  progress: number;
  error: string | null;
};

const ACCEPT = "image/jpeg,image/png,image/webp";
// While any photo is processing, check again this often (milliseconds).
export const POLL_MS = 2000;

/** Photos of one listing: gallery, uploads with progress, retry and removal. */
export function ListingMedia({
  listingId,
  canManage,
  onLoaded,
}: {
  listingId: string;
  canManage: boolean;
  /** Called with each fresh list, so other panels show the same photos. */
  onLoaded?: (media: Media[]) => void;
}) {
  const [items, setItems] = useState<Media[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const nextKey = useRef(0);
  const reload = () => setReloadKey((k) => k + 1);

  useEffect(() => {
    let cancelled = false;
    api<Media[]>(`/listings/${listingId}/media`)
      .then((media) => {
        if (cancelled) return;
        setItems(media);
        setLoadError(null);
        onLoaded?.(media);
      })
      .catch((error) => {
        if (!cancelled) setLoadError(describeError(error));
      });
    return () => {
      cancelled = true;
    };
    // onLoaded is left out: a new callback each render must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listingId, reloadKey]);

  const processing = items?.some((item) => item.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [processing, items]);

  function patchUpload(key: number, change: Partial<Upload>) {
    setUploads((list) =>
      list.map((u) => (u.key === key ? { ...u, ...change } : u)),
    );
  }

  function start(file: File, key: number) {
    uploadFile<Media>(
      `/listings/${listingId}/media?filename=${encodeURIComponent(file.name)}`,
      file,
      (progress) => patchUpload(key, { progress }),
    )
      .then(() => {
        setUploads((list) => list.filter((u) => u.key !== key));
        reload();
      })
      .catch((error) => patchUpload(key, { error: describeError(error) }));
  }

  function choose(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = ""; // choosing the same file again still fires a change
    const added = files.map((file) => ({
      key: nextKey.current++,
      file,
      progress: 0,
      error: null,
    }));
    setUploads((list) => [...list, ...added]);
    added.forEach((u) => start(u.file, u.key));
  }

  function retryUpload(upload: Upload) {
    patchUpload(upload.key, { progress: 0, error: null });
    start(upload.file, upload.key);
  }

  async function act(action: () => Promise<unknown>) {
    setActionError(null);
    try {
      await action();
    } catch (error) {
      setActionError(describeError(error));
    }
    reload();
  }

  return (
    <section aria-labelledby="media-heading">
      <h3 id="media-heading">Photos</h3>
      {loadError && <p role="alert">{loadError}</p>}
      {actionError && <p role="alert">{actionError}</p>}
      {items?.length === 0 && uploads.length === 0 && <p>No photos yet.</p>}

      {items && items.length > 0 && (
        <ul className="gallery">
          {items.map((item) => (
            <li key={item.id}>
              {item.thumbnail_url ? (
                <a href={item.url} target="_blank" rel="noopener noreferrer">
                  <img src={item.thumbnail_url} alt={item.filename} />
                </a>
              ) : (
                <div
                  className="placeholder"
                  role={item.status === "failed" ? "alert" : undefined}
                >
                  {item.status === "failed" ? item.error : "Processing…"}
                </div>
              )}
              <span className="caption">{item.filename}</span>
              {item.can_delete && (
                <div className="actions">
                  {item.status === "failed" && (
                    <button
                      type="button"
                      onClick={() =>
                        act(() =>
                          api(`/media/${item.id}/retry`, { method: "POST" }),
                        )
                      }
                    >
                      Try again
                    </button>
                  )}
                  {confirmRemove === item.id ? (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          setConfirmRemove(null);
                          act(() =>
                            api(`/media/${item.id}`, { method: "DELETE" }),
                          );
                        }}
                      >
                        Confirm removal
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmRemove(null)}
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmRemove(item.id)}
                      aria-label={`Remove ${item.filename}`}
                    >
                      Remove
                    </button>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {uploads.length > 0 && (
        <ul className="uploads" aria-label="Uploads">
          {uploads.map((upload) => (
            <li key={upload.key}>
              <span className="caption">{upload.file.name}</span>
              {upload.error ? (
                <>
                  <span role="alert">{upload.error}</span>
                  <span className="actions">
                    <button type="button" onClick={() => retryUpload(upload)}>
                      Retry upload
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setUploads((list) =>
                          list.filter((u) => u.key !== upload.key),
                        )
                      }
                    >
                      Dismiss
                    </button>
                  </span>
                </>
              ) : (
                <progress
                  value={upload.progress}
                  max={1}
                  aria-label={`Uploading ${upload.file.name}`}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {canManage && (
        <label className="file-picker">
          Add photos (JPEG, PNG or WebP)
          <input type="file" accept={ACCEPT} multiple onChange={choose} />
        </label>
      )}
    </section>
  );
}
