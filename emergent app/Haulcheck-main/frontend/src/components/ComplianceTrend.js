import { useEffect, useState } from "react";
import api from "@/lib/api";
import { TrendingUp } from "lucide-react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine,
} from "recharts";

const fmtDate = (d) => {
  try { return new Date(d).toLocaleDateString(undefined, { day: "numeric", month: "short" }); }
  catch { return d; }
};

function TrendTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const p = payload[0].payload;
  return (
    <div className="bg-slate-900 text-white rounded-md px-3 py-2 text-xs shadow-lg">
      <p className="font-semibold">{fmtDate(p.date)}</p>
      <p className="text-slate-300">Score: <span className="font-bold text-white">{p.score}</span></p>
      <p className="text-slate-400 mt-0.5">{p.expired} expired · {p.due_soon} due soon</p>
    </div>
  );
}

export function ComplianceTrend() {
  const [history, setHistory] = useState(null);

  useEffect(() => {
    api.get("/compliance/history?days=90")
      .then((res) => setHistory(res.data.history || []))
      .catch(() => setHistory([]));
  }, []);

  if (history === null) return null;

  return (
    <div data-testid="compliance-trend-card" className="bg-white border border-slate-200 rounded-md p-6 mb-6 animate-in-up">
      <div className="flex items-center gap-2 mb-1">
        <TrendingUp size={18} className="text-slate-900" />
        <h3 className="font-heading font-bold text-lg tracking-tight">Compliance Score Trend</h3>
      </div>
      <p className="text-sm text-slate-400 mb-4">Your AI compliance health score over the last 90 days.</p>
      {history.length < 2 ? (
        <div data-testid="trend-empty" className="py-12 text-center text-slate-400 text-sm">
          {history.length === 1
            ? `Today's score is ${history[0].score}. The trend line appears once we have data from more than one day — check back tomorrow.`
            : "No score history yet. Your compliance score is recorded automatically each day you visit the dashboard."}
        </div>
      ) : (
        <div style={{ width: "100%", height: 240 }} data-testid="trend-chart">
          <ResponsiveContainer>
            <LineChart data={history} margin={{ top: 8, right: 12, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" vertical={false} />
              <XAxis dataKey="date" tickFormatter={fmtDate} tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} minTickGap={24} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#94a3b8" }} axisLine={false} tickLine={false} />
              <Tooltip content={<TrendTooltip />} />
              <ReferenceLine y={85} stroke="#16A34A" strokeDasharray="4 4" strokeOpacity={0.5} />
              <ReferenceLine y={60} stroke="#EAB308" strokeDasharray="4 4" strokeOpacity={0.5} />
              <Line type="monotone" dataKey="score" stroke="#0f172a" strokeWidth={2.5} dot={{ r: 3, fill: "#0f172a" }} activeDot={{ r: 5 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
