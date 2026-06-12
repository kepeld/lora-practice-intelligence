import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Search,
  TrendingUp,
  BarChart3,
  Zap,
  Brain,
  ChevronRight,
  AlertCircle,
} from "lucide-react";

interface KPICard {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  trend?: string;
}

interface PracticeStat {
  param_name: string;
  param_value: string;
  prevalence: number;
  avg_success_score: number;
  quadrant: "common+works" | "common+fails" | "rare+works" | "rare+fails";
}

interface SearchResult {
  id: string;
  name: string;
  description: string;
  confidence: number;
}

const mockKPIs: KPICard[] = [
  { label: "Total Repositories", value: 542, icon: <TrendingUp size={20} /> },
  { label: "Enriched Repositories", value: 510, icon: <BarChart3 size={20} /> },
  { label: "HuggingFace Models", value: 189, icon: <Brain size={20} /> },
  { label: "Links Found", value: 74, icon: <Zap size={20} /> },
  { label: "Repos with Params", value: 280, icon: <TrendingUp size={20} /> },
  { label: "Extraction Coverage", value: "51.8%", icon: <BarChart3 size={20} /> },
];

const mockInsights: {
  [key: string]: PracticeStat[];
} = {
  "rare+works": [
    {
      param_name: "optimizer",
      param_value: "adamw_8bit",
      prevalence: 12,
      avg_success_score: 7.41,
      quadrant: "rare+works",
    },
    {
      param_name: "lora_alpha",
      param_value: "32",
      prevalence: 8,
      avg_success_score: 7.89,
      quadrant: "rare+works",
    },
    {
      param_name: "rank_value",
      param_value: "128",
      prevalence: 5,
      avg_success_score: 8.12,
      quadrant: "rare+works",
    },
  ],
  "common+works": [
    {
      param_name: "optimizer",
      param_value: "adam",
      prevalence: 234,
      avg_success_score: 6.78,
      quadrant: "common+works",
    },
    {
      param_name: "learning_rate",
      param_value: "0.001",
      prevalence: 189,
      avg_success_score: 6.45,
      quadrant: "common+works",
    },
    {
      param_name: "rank_value",
      param_value: "64",
      prevalence: 156,
      avg_success_score: 6.92,
      quadrant: "common+works",
    },
  ],
  "common+fails": [
    {
      param_name: "learning_rate",
      param_value: "0.1",
      prevalence: 112,
      avg_success_score: 2.34,
      quadrant: "common+fails",
    },
    {
      param_name: "optimizer",
      param_value: "sgd",
      prevalence: 87,
      avg_success_score: 3.12,
      quadrant: "common+fails",
    },
    {
      param_name: "lora_alpha",
      param_value: "8",
      prevalence: 64,
      avg_success_score: 2.89,
      quadrant: "common+fails",
    },
  ],
  "rare+fails": [
    {
      param_name: "rank_value",
      param_value: "1024",
      prevalence: 3,
      avg_success_score: 1.23,
      quadrant: "rare+fails",
    },
    {
      param_name: "lora_alpha",
      param_value: "512",
      prevalence: 2,
      avg_success_score: 0.98,
      quadrant: "rare+fails",
    },
  ],
};

const mockSearchResults: SearchResult[] = [
  {
    id: "1",
    name: "llama-7b-lora-8bit",
    description:
      "Optimized configuration for low VRAM training with AdamW 8bit quantization",
    confidence: 89.4,
  },
  {
    id: "2",
    name: "mistral-qlora-config",
    description: "QLoRA implementation for Mistral models with efficient memory usage",
    confidence: 84.2,
  },
  {
    id: "3",
    name: "falcon-40b-lora",
    description:
      "Large scale LoRA training setup for Falcon 40B with distributed training",
    confidence: 76.8,
  },
];

const QuadrantLabel = ({
  quadrant,
}: {
  quadrant: "common+works" | "common+fails" | "rare+works" | "rare+fails";
}) => {
  const labelMap = {
    "common+works": { text: "Common + Works", color: "bg-emerald-900 text-emerald-100" },
    "common+fails": { text: "Cargo Cult", color: "bg-rose-900 text-rose-100" },
    "rare+works": { text: "Hidden Insight", color: "bg-indigo-900 text-indigo-100" },
    "rare+fails": { text: "Rare + Fails", color: "bg-slate-700 text-slate-100" },
  };
  const label = labelMap[quadrant];
  return (
    <span className={`px-2.5 py-0.5 rounded text-xs font-medium ${label.color}`}>
      {label.text}
    </span>
  );
};

const ProgressBar = ({ score }: { score: number }) => {
  const percentage = (score / 10) * 100;
  return (
    <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
      <div
        className="bg-gradient-to-r from-indigo-500 to-indigo-400 h-full transition-all duration-300"
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
};

export default function Index() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<
    "rare+works" | "common+works" | "common+fails" | "rare+fails"
  >("rare+works");
  const [searchQuery, setSearchQuery] = useState("");
  const [expandedSearchId, setExpandedSearchId] = useState<string | null>(null);

  const filteredResults = mockSearchResults.filter(
    (r) =>
      r.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      r.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const tabConfig = [
    {
      id: "rare+works",
      label: "Rare + Works (Hidden Insights)",
      count: mockInsights["rare+works"].length,
    },
    {
      id: "common+works",
      label: "Common + Works",
      count: mockInsights["common+works"].length,
    },
    {
      id: "common+fails",
      label: "Common + Fails (Cargo Cult)",
      count: mockInsights["common+fails"].length,
    },
    {
      id: "rare+fails",
      label: "Rare + Fails",
      count: mockInsights["rare+fails"].length,
    },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 to-zinc-950 text-slate-100">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Brain className="w-8 h-8 text-indigo-400" />
            <h1 className="text-2xl font-bold text-slate-100">ML Underground</h1>
          </div>
        </div>
      </header>

      <div className="flex">
        {/* Main Content */}
        <main className="flex-1 overflow-auto w-full">
          <div className="p-6 md:p-8">
            {/* KPI Grid */}
            <section className="mb-12">
              <h2 className="text-xl font-semibold mb-6 text-slate-100">
                Dashboard Summary
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {mockKPIs.map((kpi, idx) => (
                  <div
                    key={idx}
                    className="bg-slate-800/50 border border-slate-700 rounded-lg p-5 hover:border-slate-600 hover:bg-slate-800/70 transition-all duration-200 group"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <h3 className="text-sm font-medium text-slate-300">
                        {kpi.label}
                      </h3>
                      <div className="text-indigo-400/60 group-hover:text-indigo-400 transition-colors">
                        {kpi.icon}
                      </div>
                    </div>
                    <p className="text-3xl font-bold text-slate-100 mb-1">
                      {kpi.value}
                    </p>
                    {kpi.trend && (
                      <p className="text-xs text-emerald-400">{kpi.trend}</p>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {/* Insights Section */}
            <section className="mb-12">
              <h2 className="text-xl font-semibold mb-6 text-slate-100">
                Insights Matrix - 4-Quadrant Practice Analysis
              </h2>

              {/* Tab Selector */}
              <div className="flex flex-wrap gap-2 mb-6 p-1 bg-slate-800/30 rounded-lg border border-slate-700 w-fit">
                {tabConfig.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as never)}
                    className={`px-4 py-2 rounded-md text-sm font-medium transition-all duration-200 whitespace-nowrap ${
                      activeTab === tab.id
                        ? "bg-indigo-500/30 text-indigo-100 border border-indigo-500/50"
                        : "text-slate-400 hover:text-slate-300 border border-transparent"
                    }`}
                  >
                    {tab.label}{" "}
                    <span className="text-xs ml-2 opacity-70">({tab.count})</span>
                  </button>
                ))}
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-700">
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Parameter Name
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Extracted Value
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Prevalence
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Avg Success Score
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                        Quadrant
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {mockInsights[activeTab].map((stat, idx) => (
                      <tr
                        key={idx}
                        onClick={() =>
                          navigate(`/insight/${stat.param_name}/${stat.param_value}`)
                        }
                        className="border-b border-slate-800 hover:bg-slate-800/30 transition-colors duration-150 cursor-pointer"
                      >
                        <td className="px-4 py-4 text-sm font-medium text-slate-100">
                          {stat.param_name}
                        </td>
                        <td className="px-4 py-4 text-sm text-slate-300 font-mono">
                          {stat.param_value}
                        </td>
                        <td className="px-4 py-4 text-sm text-slate-300">
                          <span className="bg-slate-800 px-2.5 py-1 rounded text-xs">
                            {stat.prevalence}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <div className="max-w-xs space-y-1.5">
                            <div className="text-slate-300">
                              {stat.avg_success_score.toFixed(2)}/10
                            </div>
                            <ProgressBar score={stat.avg_success_score} />
                          </div>
                        </td>
                        <td className="px-4 py-4 text-sm">
                          <QuadrantLabel quadrant={stat.quadrant} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Search Section */}
            <section>
              <h2 className="text-xl font-semibold mb-6 text-slate-100">
                AI Semantic Search
              </h2>

              {/* Search Input */}
              <div className="mb-6 relative">
                <Search className="absolute left-4 top-3.5 w-5 h-5 text-slate-500" />
                <input
                  type="text"
                  placeholder="Search LoRA practices, e.g., 'low vram llama 3 configuration with 8bit adamw'"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-slate-800/50 border border-slate-700 rounded-lg pl-12 pr-4 py-3 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/30 transition-all duration-200"
                />
              </div>

              {/* Search Results */}
              <div className="space-y-3">
                {filteredResults.length > 0 ? (
                  filteredResults.map((result) => (
                    <div
                      key={result.id}
                      className="bg-slate-800/50 border border-slate-700 rounded-lg overflow-hidden hover:border-slate-600 transition-all duration-200"
                    >
                      <button
                        onClick={() =>
                          setExpandedSearchId(
                            expandedSearchId === result.id ? null : result.id
                          )
                        }
                        className="w-full px-6 py-4 flex items-center justify-between hover:bg-slate-800/70 transition-colors"
                      >
                        <div className="flex-1 text-left">
                          <h3 className="font-semibold text-slate-100 mb-1">
                            {result.name}
                          </h3>
                          <div className="flex items-center gap-4">
                            <p className="text-sm text-slate-400">
                              {result.description}
                            </p>
                            <span className="ml-auto px-3 py-1 bg-indigo-500/20 text-indigo-100 rounded text-xs font-medium whitespace-nowrap border border-indigo-500/30">
                              Score: {result.confidence.toFixed(1)}%
                            </span>
                          </div>
                        </div>
                        <ChevronRight
                          size={20}
                          className={`ml-4 text-slate-500 transition-transform duration-200 ${
                            expandedSearchId === result.id ? "rotate-90" : ""
                          }`}
                        />
                      </button>

                      {expandedSearchId === result.id && (
                        <div className="border-t border-slate-700 px-6 py-4 bg-slate-900/50">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                            <div>
                              <p className="text-slate-400 mb-1">Configuration</p>
                              <code className="text-indigo-300 text-xs bg-slate-900 p-2 rounded block">
                                rank_value: 64, lora_alpha: 16
                              </code>
                            </div>
                            <div>
                              <p className="text-slate-400 mb-1">Success Metrics</p>
                              <p className="text-slate-300">
                                Avg Score: <span className="text-emerald-400">7.8/10</span>
                              </p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                ) : searchQuery ? (
                  <div className="bg-slate-800/50 border border-slate-700 rounded-lg p-6 flex items-center gap-3">
                    <AlertCircle size={20} className="text-slate-500" />
                    <p className="text-slate-400">
                      No results found for "{searchQuery}"
                    </p>
                  </div>
                ) : (
                  <div className="text-center py-8 text-slate-500">
                    Enter a search query to find LoRA training practices
                  </div>
                )}
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
