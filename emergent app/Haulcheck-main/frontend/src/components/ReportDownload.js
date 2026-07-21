import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { FileDown, ChevronDown } from "lucide-react";
import { downloadPdf } from "@/lib/download";

// path: report endpoint path (e.g. "/reports/defects" or "/pmi/<id>/report")
// filename: base filename. evidence: show "+ evidence files" option.
export function ReportDownload({ path, filename, testid, evidence = false, label = "Download PDF" }) {
  if (!evidence) {
    return (
      <Button data-testid={testid} variant="outline" onClick={() => downloadPdf(path, filename)} className="rounded-md gap-2 border-slate-300">
        <FileDown size={16} /> {label}
      </Button>
    );
  }
  const packName = filename.replace(/\.pdf$/, "-pack.pdf");
  const sep = path.includes("?") ? "&" : "?";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button data-testid={testid} variant="outline" className="rounded-md gap-2 border-slate-300">
          <FileDown size={16} /> {label} <ChevronDown size={14} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem data-testid={`${testid}-summary`} onClick={() => downloadPdf(path, filename)}>
          Report (summary)
        </DropdownMenuItem>
        <DropdownMenuItem data-testid={`${testid}-evidence`} onClick={() => downloadPdf(`${path}${sep}include_files=true`, packName)}>
          Report + evidence files
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
