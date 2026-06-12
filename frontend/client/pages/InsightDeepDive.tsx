import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Star,
  GitFork,
  Award,
  TrendingUp,
  Code2,
  Download,
  Heart,
  Zap,
  CheckCircle2,
} from "lucide-react";
import { useState } from "react";

interface Repository {
  repo_name: string;
  star_count: number;
  forks_count: number;
  primary_language: string;
  extraction_confidence: number;
}

interface HuggingFaceModel {
  model_id: string;
  base_model: string;
  downloads: number;
  likes: number;
  fine_tune_fan_out: number;
  composite_success_score: number;
}

interface PracticeSummary {
  param_name: string;
  param_value: string;
  prevalence: number;
  avg_success_score: number;
  quadrant: "common+works" | "common+fails" | "rare+works" | "rare+fails";
}

const mockRepositories: Repository[] = [
  {
    repo_name: "huggingface/peft",
    star_count: 12400,
    forks_count: 1850,
    primary_language: "Python",
    extraction_confidence: 0.98,
  },
  {
    repo_name: "openai/gpt-3-tokenizer",
    star_count: 4200,
    forks_count: 620,
    primary_language: "Python",
    extraction_confidence: 0.92,
  },
  {
    repo_name: "meta-llama/llama-recipes",
    star_count: 8900,
    forks_count: 1340,
    primary_language: "Python",
    extraction_confidence: 0.88,
  },
  {
    repo_name: "together-ai/open-instruct",
    star_count: 2150,
    forks_count: 340,
    primary_language: "Python",
    extraction_confidence: 0.85,
  },
  {
    repo_name: "gpt-bedrock/llm-toolkit",
    star_count: 5600,
    forks_count: 890,
    primary_language: "Python",
    extraction_confidence: 0.79,
  },
];

const mockHuggingFaceModels: HuggingFaceModel[] = [
  {
    model_id: "meta-llama/Llama-2-7b-hf",
    base_model: "meta-llama/Llama-2-7b",
    downloads: 15400000,
    likes: 42800,
    fine_tune_fan_out: 8943,
    composite_success_score: 8.93,
  },
  {
    model_id: "mistralai/Mistral-7B-v0.1",
    base_model: "mistralai/Mistral-7B",
    downloads: 8200000,
    likes: 28900,
    fine_tune_fan_out: 5640,
    composite_success_score: 8.67,
  },
  {
    model_id: "tiiuae/falcon-7b",
    base_model: "tiiuae/falcon-7b-base",
    downloads: 6800000,
    likes: 18700,
    fine_tune_fan_out: 3210,
    composite_success_score: 8.41,
  },
  {
    model_id: "bigscience/bloom-7b1",
    base_model: "bigscience/bloom",
    downloads: 5200000,
    likes: 12300,
    fine_tune_fan_out: 2145,
    composite_success_score: 8.12,
  },
  {
    model_id: "EleutherAI/gpt-j-6B",
    base_model: "EleutherAI/gpt-j-6B",
    downloads: 4100000,
    likes: 9870,
    fine_tune_fan_out: 1890,
    composite_success_score: 7.84,
  },
];

const mockPracticeSummary: PracticeSummary = {
  param_name: "optimizer",
  param_value: "adamw_8bit",
  prevalence: 12,
  avg_success_score: 7.41,
  quadrant: "rare+works",
};

const QuadrantBadge = ({
  quadrant,
}: {
  quadrant: "common+works" | "common+fails" | "rare+works" | "rare+fails";
}) => {
  const badgeMap = {
    "common+works": {
      text: "Common + Works",
      color: "bg-emerald-900/40 text-emerald-200 border-emerald-800",
    },
    "common+fails": {
      text: "Cargo Cult",
      color: "bg-rose-900/40 text-rose-200 border-rose-800",
    },
    "rare+works": {
      text: "🔥 Hidden Insight",
      color: "bg-indigo-900/40 text-indigo-200 border-indigo-800",
    },
    "rare+fails": {
      text: "Rare + Fails",
      color: "bg-slate-700/40 text-slate-300 border-slate-700",
    },
  };
  const badge = badgeMap[quadrant];
  return (
    <span
      className={`px-4 py-2 rounded-lg text-sm font-semibold border ${badge.color}`}
    >
      {badge.text}
    </span>
  );
};

const ConfidenceMeter = ({ confidence }: { confidence: number }) => {
  const percentage = confidence * 100;
  const color =
    confidence >= 0.95
      ? "from-emerald-500 to-emerald-400"
      : confidence >= 0.85
        ? "from-amber-500 to-amber-400"
        : "from-slate-500 to-slate-400";

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-300">
          {percentage.toFixed(0)}% confidence
        </span>
      </div>
      <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
        <div
          className={`bg-gradient-to-r ${color} h-full transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};

const StatCard = ({ label, value, icon, highlight = false }: any) => (
  <div
    className={`flex flex-col gap-2 p-6 rounded-lg border ${
      highlight
        ? "bg-gradient-to-br from-amber-900/20 to-orange-900/10 border-amber-800/50"
        : "bg-slate-800/50 border-slate-700"
    }`}
  >
    <div className="flex items-center gap-2">
      <span className={`${highlight ? "text-amber-400" : "text-slate-400"}`}>
        {icon}
      </span>
      <p className="text-xs uppercase tracking-widest text-slate-400 font-medium">
        {label}
      </p>
    </div>
    <p className={`text-3xl font-bold ${highlight ? "text-amber-100" : "text-slate-100"}`}>
      {value}
    </p>
  </div>
);

export default function InsightDeepDive() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<"repos" | "models">("repos");

  const practice = mockPracticeSummary;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-950 to-zinc-950 text-slate-100">
      {/* Header */}
      <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-50">
        <div className="px-6 md:px-8 py-4">
          <button
            onClick={() => navigate("/")}
            className="flex items-center gap-2 text-indigo-400 hover:text-indigo-300 transition-colors mb-4 font-medium"
          >
            <ArrowLeft size={18} />
            Back to All Insights
          </button>
          <h1 className="text-2xl font-bold text-slate-100">Insight Deep Dive</h1>
        </div>
      </header>

      <main className="p-6 md:p-8">
        {/* Practice Summary Hero Card */}
        <section className="mb-10">
          <div className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 border border-slate-700 rounded-xl p-8 space-y-6">
            {/* Title Row */}
            <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
              <div>
                <p className="text-sm uppercase tracking-widest text-slate-400 mb-2">
                  Analyzed Practice
                </p>
                <div className="font-mono text-2xl md:text-3xl font-bold text-slate-100 break-all">
                  <span className="text-slate-500">{practice.param_name}:</span>{" "}
                  <span className="text-indigo-300">{practice.param_value}</span>
                </div>
              </div>
              <QuadrantBadge quadrant={practice.quadrant} />
            </div>

            {/* Metrics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <StatCard
                label="Average Impact Score"
                value={`${practice.avg_success_score.toFixed(2)}/10`}
                icon={<Award size={20} />}
                highlight={true}
              />
              <StatCard
                label="Market Prevalence"
                value={`${practice.prevalence} repos`}
                icon={<TrendingUp size={20} />}
              />
              <div className="flex flex-col gap-2 p-6 rounded-lg bg-slate-800/50 border border-slate-700">
                <div className="flex items-center gap-2">
                  <CheckCircle2 size={20} className="text-emerald-400" />
                  <p className="text-xs uppercase tracking-widest text-slate-400 font-medium">
                    Extraction Quality
                  </p>
                </div>
                <p className="text-sm text-emerald-300 font-semibold">
                  High Confidence
                </p>
                <ConfidenceMeter confidence={0.94} />
              </div>
            </div>
          </div>
        </section>

        {/* Tabs */}
        <section>
          <div className="flex gap-2 mb-6 border-b border-slate-800">
            <button
              onClick={() => setActiveTab("repos")}
              className={`px-4 py-3 font-medium text-sm transition-all duration-200 border-b-2 ${
                activeTab === "repos"
                  ? "text-indigo-400 border-indigo-500 bg-indigo-500/10"
                  : "text-slate-400 border-transparent hover:text-slate-300"
              }`}
            >
              <div className="flex items-center gap-2">
                <Code2 size={18} />
                GitHub Repositories
              </div>
            </button>
            <button
              onClick={() => setActiveTab("models")}
              className={`px-4 py-3 font-medium text-sm transition-all duration-200 border-b-2 ${
                activeTab === "models"
                  ? "text-indigo-400 border-indigo-500 bg-indigo-500/10"
                  : "text-slate-400 border-transparent hover:text-slate-300"
              }`}
            >
              <div className="flex items-center gap-2">
                <Zap size={18} />
                HuggingFace Models
              </div>
            </button>
          </div>

          {/* Repositories Tab */}
          {activeTab === "repos" && (
            <div className="space-y-3">
              <p className="text-sm text-slate-400 mb-4">
                {mockRepositories.length} repositories where this configuration was detected
              </p>
              {mockRepositories.map((repo, idx) => (
                <div
                  key={idx}
                  className="group bg-slate-800/30 border border-slate-700 rounded-lg p-5 hover:border-slate-600 hover:bg-slate-800/50 hover:-translate-y-0.5 transition-all duration-200 cursor-pointer"
                >
                  <div className="space-y-4">
                    {/* Repo Name and Language */}
                    <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                      <div className="flex-1">
                        <a
                          href={`https://github.com/${repo.repo_name}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-lg font-semibold text-indigo-300 hover:text-indigo-200 transition-colors"
                        >
                          {repo.repo_name}
                        </a>
                        <div className="mt-1 inline-flex items-center gap-2 px-3 py-1 bg-slate-900/50 rounded-md border border-slate-700">
                          <Code2 size={14} className="text-slate-500" />
                          <span className="text-xs font-medium text-slate-300">
                            {repo.primary_language}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Stats Row */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="flex items-center gap-2 p-2 bg-slate-900/30 rounded border border-slate-700/50">
                        <Star size={16} className="text-amber-400" />
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-400">Stars</span>
                          <span className="font-semibold text-slate-100">
                            {(repo.star_count / 1000).toFixed(1)}k
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 p-2 bg-slate-900/30 rounded border border-slate-700/50">
                        <GitFork size={16} className="text-indigo-400" />
                        <div className="flex flex-col">
                          <span className="text-xs text-slate-400">Forks</span>
                          <span className="font-semibold text-slate-100">
                            {(repo.forks_count / 1000).toFixed(1)}k
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Confidence Meter */}
                    <div className="pt-2 border-t border-slate-700/50">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-medium text-slate-300">
                          Extraction Confidence
                        </span>
                        <span className="text-xs font-semibold text-emerald-400">
                          AST Parser
                        </span>
                      </div>
                      <ConfidenceMeter confidence={repo.extraction_confidence} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* HuggingFace Models Tab */}
          {activeTab === "models" && (
            <div className="space-y-4">
              <p className="text-sm text-slate-400 mb-4">
                {mockHuggingFaceModels.length} validated models using this configuration
              </p>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {mockHuggingFaceModels.map((model, idx) => (
                  <div
                    key={idx}
                    className="group bg-slate-800/30 border border-slate-700 rounded-lg p-6 hover:border-indigo-600/50 hover:bg-slate-800/60 hover:-translate-y-0.5 transition-all duration-200"
                  >
                    {/* Model ID and Base */}
                    <div className="mb-4 pb-4 border-b border-slate-700/50">
                      <a
                        href={`https://huggingface.co/${model.model_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-base font-semibold text-indigo-300 hover:text-indigo-200 transition-colors break-all"
                      >
                        {model.model_id}
                      </a>
                      <p className="text-xs text-slate-400 mt-1">
                        Base: <span className="text-slate-300">{model.base_model}</span>
                      </p>
                    </div>

                    {/* Score Badge */}
                    <div className="mb-4">
                      <div className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-amber-900/40 to-orange-900/30 border border-amber-800/50 rounded-lg">
                        <Award size={18} className="text-amber-400" />
                        <span className="font-bold text-amber-100">
                          Score: {model.composite_success_score.toFixed(2)}
                        </span>
                      </div>
                    </div>

                    {/* Metrics Grid */}
                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-slate-900/50 border border-slate-700/50 rounded-lg p-3">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Download size={14} className="text-slate-500" />
                          <span className="text-xs text-slate-400 font-medium">Downloads</span>
                        </div>
                        <p className="font-bold text-slate-100">
                          {(model.downloads / 1000000).toFixed(1)}M
                        </p>
                      </div>
                      <div className="bg-slate-900/50 border border-slate-700/50 rounded-lg p-3">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Heart size={14} className="text-rose-500" />
                          <span className="text-xs text-slate-400 font-medium">Likes</span>
                        </div>
                        <p className="font-bold text-slate-100">
                          {(model.likes / 1000).toFixed(1)}k
                        </p>
                      </div>
                      <div className="col-span-2 bg-slate-900/50 border border-slate-700/50 rounded-lg p-3">
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <TrendingUp size={14} className="text-indigo-400" />
                          <span className="text-xs text-slate-400 font-medium">
                            Fine-Tune Fan-Out
                          </span>
                        </div>
                        <p className="font-bold text-slate-100">
                          {model.fine_tune_fan_out.toLocaleString()} models derived
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
