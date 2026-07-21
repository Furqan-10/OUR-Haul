import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useSearchParams } from "react-router-dom";
import { InspectionsPanel } from "@/pages/Inspections";
import { DefectsPanel } from "@/pages/Defects";
import { WheelSecurityPanel } from "@/pages/WheelSecurity";
import { WalkaroundPanel } from "@/pages/Walkaround";
import { WeeklyWalkaroundPanel } from "@/pages/WeeklyWalkaround";
import { ServicePanel } from "@/pages/Service";

const VALID = ["pmi", "walkaround", "weekly", "defects", "service", "wheel"];

export default function Maintenance() {
  const [params] = useSearchParams();
  const initial = VALID.includes(params.get("tab")) ? params.get("tab") : "pmi";
  return (
    <div data-testid="maintenance-page">
      <div className="mb-6">
        <p className="text-xs uppercase tracking-[0.2em] text-slate-500 font-semibold">Compliance</p>
        <h1 className="font-heading text-3xl sm:text-4xl font-black tracking-tight text-slate-900 mt-1">Maintenance</h1>
        <p className="text-slate-500 text-sm mt-1">PMI inspections, defects, servicing & wheel security</p>
      </div>
      <Tabs defaultValue={initial}>
        <TabsList className="mb-6">
          <TabsTrigger value="pmi" data-testid="tab-pmi">PMI Inspections</TabsTrigger>
          <TabsTrigger value="walkaround" data-testid="tab-walkaround">Daily Checks</TabsTrigger>
          <TabsTrigger value="weekly" data-testid="tab-weekly">Weekly Checks</TabsTrigger>
          <TabsTrigger value="defects" data-testid="tab-defects">Defects</TabsTrigger>
          <TabsTrigger value="service" data-testid="tab-service">Vehicles Service</TabsTrigger>
          <TabsTrigger value="wheel" data-testid="tab-wheel">Wheel Security</TabsTrigger>
        </TabsList>
        <TabsContent value="pmi"><InspectionsPanel embedded /></TabsContent>
        <TabsContent value="walkaround"><WalkaroundPanel embedded /></TabsContent>
        <TabsContent value="weekly"><WeeklyWalkaroundPanel /></TabsContent>
        <TabsContent value="defects"><DefectsPanel embedded /></TabsContent>
        <TabsContent value="service"><ServicePanel /></TabsContent>
        <TabsContent value="wheel"><WheelSecurityPanel embedded /></TabsContent>
      </Tabs>
    </div>
  );
}
