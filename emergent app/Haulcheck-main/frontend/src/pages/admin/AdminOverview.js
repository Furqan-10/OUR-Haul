import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Building2, Users, Database, FileStack, TrendingUp } from "lucide-react";
import { toast } from "sonner";

const Tile = ({ icon: Icon, label, value, sub, testid }) => (
  <div className="bg-slate-900 border border-slate-800 rounded-md p-4" data-testid={testid}>
    <div className="flex items-center gap-2 text-slate-400">
      <Icon size={15} />
      <span className="text-[11px] font-semibold uppercase tracking-wider">{label}</span>
    </div>
    <p className="font-heading text-3xl font-black text-white mt-1.5">{value}</p>
    {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
  </div>
);

/** Simple inline bar chart — avoids pulling a charting dependency for one sparkline. */
const Signups = ({ data }) => {
  if (!data?.length) {
    return <p className="text-sm text-slate-500">No signups in this window.</p>;
  }
  const max = Math.max(...data.map((d) => d.count), 1);
  return (
    <div className="flex items-end gap-1 h-28" data-testid="signup-chart">
      {data.map((d) => (
        <div key={d.date} className="flex-1 flex flex-col items-center gap-1 group">
          <div
            className="w-full bg-amber-400/70 group-hover:bg-amber-300 rounded-sm transition-colors"
            style={{ height: `${Math.max((d.count / max) * 100, 4)}%` }}
            title={`${d.date}: ${d.count}`}
          />
        </div>
      ))}
    </div>
  );
};

export default function AdminOverview() {
  const [metrics, setMetrics] = useState(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get(`/admin/metrics?days=${days}`)
      .then((r) => setMetrics(r.data))
      .catch(() => toast.error("Could not load platform metrics"))
      .finally(() => setLoading(false));
  }, [days]);

  if (loading && !metrics) {
    return <p className="text-slate-500 text-sm" data-testid="admin-overview-loading">Loading metrics…</p>;
  }
  if (!metrics) return null;

  const { organisations: orgs, users, records, storage, signups_by_day: signups } = metrics;

  return (
    <div data-testid="admin-overview">
      <div className="flex flex-wrap items-end justify-between gap-3 mb-6">
        <div>
          <p className="text-[11px] uppercase tracking-[0.2em] text-slate-500 font-semibold">Platform</p>
          <h1 className="font-heading text-3xl font-black tracking-tight text-white mt-1">Overview</h1>
        </div>
        <select
          data-testid="metrics-window"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="bg-slate-900 border border-slate-700 rounded-md px-3 py-1.5 text-sm"
        >
          {[7, 30, 90, 365].map((d) => (
            <option key={d} value={d}>Last {d} days</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        <Tile icon={Building2} label="Tenants" value={orgs.total} testid="tile-orgs"
          sub={orgs.suspended ? `${orgs.suspended} suspended` : "all active"} />
        <Tile icon={Users} label="Users" value={users.total} testid="tile-users"
          sub={`${users.active_in_window} active in ${days}d`} />
        <Tile icon={TrendingUp} label={`New in ${days}d`} value={users.new_in_window}
          testid="tile-new" sub={`${orgs.new_in_window} new tenants`} />
        <Tile icon={Database} label="Records" value={records.total.toLocaleString()}
          testid="tile-records" sub={`${storage.files} files stored`} />
      </div>

      <section className="bg-slate-900 border border-slate-800 rounded-md p-5 mb-6">
        <h2 className="font-heading text-lg font-bold text-white mb-3">Signups</h2>
        <Signups data={signups} />
      </section>

      <section className="bg-slate-900 border border-slate-800 rounded-md p-5" data-testid="records-breakdown">
        <div className="flex items-center gap-2 mb-3">
          <FileStack size={16} className="text-slate-400" />
          <h2 className="font-heading text-lg font-bold text-white">Records by type</h2>
        </div>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-1.5">
          {Object.entries(records.by_collection)
            .sort((a, b) => b[1] - a[1])
            .map(([name, count]) => (
              <div key={name} className="flex justify-between text-sm border-b border-slate-800/70 py-1">
                <span className="text-slate-400">{name.replace(/_/g, " ")}</span>
                <span className="font-semibold text-slate-200">{count.toLocaleString()}</span>
              </div>
            ))}
        </div>
      </section>
    </div>
  );
}
