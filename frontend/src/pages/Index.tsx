import Navbar from "@/components/trace911/Navbar";
import AudioPanel from "@/components/trace911/AudioPanel";
import TranscriptPanel from "@/components/trace911/TranscriptPanel";
import MetricsAnalysisPanel from "@/components/trace911/MetricsAnalysisPanel";

const Index = () => {
  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <Navbar />
      <main className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-3 gap-4 p-4 overflow-y-auto md:overflow-hidden">
        <AudioPanel />
        <TranscriptPanel />
        <MetricsAnalysisPanel />
      </main>
    </div>
  );
};

export default Index;
