/**
 * Мок-транспорт: отдаёт те же структуры, что и бэкенд, но читает снимок данных
 * из public/mock. Нужен, чтобы демонстрировать фронт без поднятого API и
 * чтобы UI можно было разрабатывать параллельно с бэкендом.
 */
import { ApiError } from './client';
import type {
  AiRecommendations,
  Analysis,
  AnalysisStage,
  LanguageFacet,
  OwnedRepo,
  Paged,
  PlatformStats,
  RatingQuery,
  RepoReport,
  RepoSummary,
  User,
} from './types';

const BASE = `${import.meta.env.BASE_URL ?? '/'}mock`;

async function loadJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/${path}`);
  if (!res.ok) throw new ApiError(`Мок-данные не найдены: ${path}`, res.status, 'mock_not_found');
  return (await res.json()) as T;
}

let reposCache: Promise<{ items: RepoSummary[]; total: number }> | null = null;
function allRepos() {
  if (!reposCache) reposCache = loadJson<{ items: RepoSummary[]; total: number }>('repos.json');
  return reposCache;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function fileNameFor(fullPath: string) {
  return `${fullPath.replace('/', '__')}.json`;
}

export const mockApi = {
  async getRating(q: RatingQuery): Promise<Paged<RepoSummary>> {
    await sleep(120);
    const { items } = await allRepos();
    const page = q.page ?? 1;
    const pageSize = q.page_size ?? 25;
    const needle = (q.query ?? '').trim().toLowerCase();

    let rows = items.filter((r) => {
      if (needle && !(`${r.full_path} ${r.description ?? ''}`.toLowerCase().includes(needle))) return false;
      if (q.language && (r.primary_language ?? '—') !== q.language) return false;
      if (q.has_ci != null && r.has_ci !== q.has_ci) return false;
      if (q.security_status && r.security_status !== q.security_status) return false;
      if (q.min_coverage != null && r.coverage < q.min_coverage) return false;
      return true;
    });

    const dir = q.order === 'asc' ? 1 : -1;
    const value = (r: RepoSummary) => {
      switch (q.sort) {
        case 'likes':
          return r.likes ?? 0;
        case 'activity':
          return r.last_activity_at ? Date.parse(r.last_activity_at) : 0;
        case 'name':
          return 0;
        default:
          return r.total_score ?? -1;
      }
    };
    rows = [...rows].sort((a, b) => {
      if (q.sort === 'name') return dir * a.full_path.localeCompare(b.full_path);
      const diff = value(a) - value(b);
      if (diff !== 0) return dir * diff;
      return (b.total_score ?? -1) - (a.total_score ?? -1);
    });

    const start = (page - 1) * pageSize;
    return { items: rows.slice(start, start + pageSize), total: rows.length, page, page_size: pageSize };
  },

  async getRepo(owner: string, name: string): Promise<RepoReport> {
    await sleep(150);
    return loadJson<RepoReport>(`reports/${fileNameFor(`${owner}/${name}`)}`);
  },

  /**
   * В снимке модели нет: после паузы, как у настоящей генерации, возвращаются
   * базовые рекомендации. model: null — интерфейс честно пишет, что ИИ не вызывался.
   */
  async generateAiRecommendations(fullPath: string): Promise<AiRecommendations> {
    await sleep(1800);
    const report = await loadJson<RepoReport>(`reports/${fileNameFor(fullPath)}`);
    return {
      recommendations: report.recommendations.map((r) => ({ ...r, id: `ai-${r.id}` })),
      model: null,
      generated_at: new Date().toISOString(),
    };
  },

  async getLanguages(): Promise<LanguageFacet[]> {
    return loadJson<LanguageFacet[]>('languages.json');
  },

  async getStats(): Promise<PlatformStats> {
    return loadJson<PlatformStats>('stats.json');
  },

  async getMe(): Promise<User> {
    const data = await loadJson<{ user: User }>('me.json');
    return data.user;
  },

  async getMyRepos(): Promise<OwnedRepo[]> {
    await sleep(200);
    const data = await loadJson<{ repos: OwnedRepo[] }>('me.json');
    return data.repos;
  },

  /** Имитация асинхронного анализа: очередь → сбор данных → расчёт → отчёт. */
  async startAnalysis(fullPath: string): Promise<Analysis> {
    const id = `mock-${Date.now()}`;
    const analysis: Analysis = {
      id,
      repo_full_path: fullPath,
      status: 'queued',
      progress: 0,
      stages: MOCK_STAGES.map((s, i) => ({ ...s, status: i === 0 ? 'running' : 'pending' })),
      started_at: new Date().toISOString(),
      finished_at: null,
      error: null,
      report: null,
    };
    runs.set(id, analysis);
    void advance(id, fullPath);
    return structuredClone(analysis);
  },

  async getAnalysis(id: string): Promise<Analysis> {
    const a = runs.get(id);
    if (!a) throw new ApiError('Запуск анализа не найден', 404, 'not_found');
    // Копия обязательна: поллинг мутирует один и тот же объект, а React Query
    // сравнивает ссылки — без копии прогресс на экране не обновлялся бы.
    return structuredClone(a);
  },
};

const MOCK_STAGES: Omit<AnalysisStage, 'status'>[] = [
  { key: 'queue', title: 'Постановка в очередь' },
  { key: 'clone', title: 'Получение рабочей копии и Git-истории' },
  { key: 'platform', title: 'Метаданные платформы: issues, MR, релизы, лайки' },
  { key: 'appsec', title: 'Результаты AppSec SourceCraft' },
  { key: 'score', title: 'Расчёт Repo Health Score' },
  { key: 'recommendations', title: 'Формирование рекомендаций' },
];

const runs = new Map<string, Analysis>();

async function advance(id: string, fullPath: string) {
  const durations = [700, 1600, 1200, 900, 700, 600];
  for (let i = 0; i < MOCK_STAGES.length; i += 1) {
    await sleep(durations[i]);
    const a = runs.get(id);
    if (!a) return;
    a.status = 'running';
    a.stages = a.stages.map((s, idx) => ({
      ...s,
      status: idx < i + 1 ? 'done' : idx === i + 1 ? 'running' : 'pending',
      detail:
        idx === 3 && i >= 3
          ? 'AppSec вернул 403: категория Security останется без данных'
          : s.detail ?? null,
    }));
    if (i === 3) {
      a.stages[3].status = 'skipped';
    }
    a.progress = Math.round(((i + 1) / MOCK_STAGES.length) * 100);
  }

  const a = runs.get(id);
  if (!a) return;
  try {
    const report = await loadJson<RepoReport>(`reports/${fileNameFor(fullPath)}`);
    const now = new Date().toISOString();
    a.report = {
      ...report,
      analyzed_at: now,
      collection: { ...report.collection, collected_at: now },
      history: [...(report.history ?? []), { analyzed_at: now, total: report.score.total }],
    };
    a.status = 'succeeded';
    a.progress = 100;
    a.finished_at = now;
    a.stages = a.stages.map((s) => (s.status === 'skipped' ? s : { ...s, status: 'done' }));
  } catch (e) {
    a.status = 'failed';
    a.error = e instanceof Error ? e.message : 'Не удалось выполнить анализ';
    a.finished_at = new Date().toISOString();
  }
}
