import { useState } from "react";
import api, { API } from "@/lib/api";
import { Upload, FileText, X, Loader2 } from "lucide-react";
import { toast } from "sonner";

const authUrl = (fileId) => `${API}/files/${fileId}?auth=${localStorage.getItem("token") || ""}`;
const isImage = (ct) => (ct || "").startsWith("image/");

export function FileUpload({ attachments = [], onChange, testid = "file-upload", accept = "image/*,application/pdf", label = "Upload photos / scans (image or PDF)" }) {
  const [busy, setBusy] = useState(false);

  const handleFiles = async (files) => {
    if (!files?.length) return;
    setBusy(true);
    try {
      const uploaded = [];
      for (const file of Array.from(files)) {
        const fd = new FormData();
        fd.append("file", file);
        const res = await api.post("/upload", fd, { headers: { "Content-Type": "multipart/form-data" } });
        uploaded.push({ file_id: res.data.file_id, filename: res.data.filename, content_type: res.data.content_type });
      }
      onChange([...attachments, ...uploaded]);
      toast.success(`${uploaded.length} file${uploaded.length > 1 ? "s" : ""} uploaded`);
    } catch (e) {
      toast.error("Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const removeAt = (i) => onChange(attachments.filter((_, idx) => idx !== i));

  return (
    <div>
      <label
        data-testid={`${testid}-drop`}
        className="flex items-center justify-center gap-2 border-2 border-dashed border-slate-300 rounded-md py-4 px-3 text-sm text-slate-500 cursor-pointer hover:border-slate-400 hover:bg-slate-50 transition-colors"
      >
        {busy ? <Loader2 size={18} className="animate-spin" /> : <Upload size={18} />}
        <span>{busy ? "Uploading…" : label}</span>
        <input
          data-testid={`${testid}-input`}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
          disabled={busy}
        />
      </label>

      {attachments.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3" data-testid={`${testid}-list`}>
          {attachments.map((a, i) => (
            <div key={a.file_id} className="relative group border border-slate-200 rounded-md overflow-hidden w-20 h-20 bg-slate-50 flex items-center justify-center">
              {isImage(a.content_type) ? (
                <img src={authUrl(a.file_id)} alt={a.filename} className="object-cover w-full h-full" />
              ) : (
                <FileText size={26} className="text-slate-400" />
              )}
              <button
                type="button"
                data-testid={`${testid}-remove-${i}`}
                onClick={() => removeAt(i)}
                className="absolute top-0.5 right-0.5 bg-black/70 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X size={12} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AttachmentThumbs({ attachments = [] }) {
  if (!attachments.length) return null;
  return (
    <div className="flex flex-wrap gap-2 mt-3" data-testid="attachment-thumbs">
      {attachments.map((a) => (
        <a
          key={a.file_id}
          href={authUrl(a.file_id)}
          target="_blank"
          rel="noopener noreferrer"
          className="block border border-slate-200 rounded-md overflow-hidden w-16 h-16 bg-slate-50 flex items-center justify-center hover:border-slate-400 transition-colors"
          title={a.filename}
        >
          {isImage(a.content_type) ? (
            <img src={authUrl(a.file_id)} alt={a.filename} className="object-cover w-full h-full" />
          ) : (
            <FileText size={22} className="text-slate-400" />
          )}
        </a>
      ))}
    </div>
  );
}
