/**
 * Типы ответов API SourceCraft Repo Health.
 * Это же — контракт для бэкенда, см. docs/api-contract.md и docs/openapi.yaml.
 */

export type CategoryKey =
  | 'security'
  | 'code_health'
  | 'activity'
  | 'documentation'
  | 'cicd'
  | 'issues';

/**
 * ok             — данные собраны полностью
 * partial        — часть сигналов недоступна, оценка посчитана по остальным
 * no_data        — источник недоступен, категория исключена из Score
 * not_applicable — сущности нет (например, трекер задач не используется)
 */
export type DataStatus = 'ok' | 'partial' | 'no_data' | 'not_applicable';

export type Priority = 'critical' | 'high' | 'medium' | 'low' | 'info';

export type SourceKey = 'git_clone' | 'platform_api' | 'platform_cli' | 'appsec_api';

export interface MetricValue {
  key: string;
  label: string;
  value: number | string | boolean | string[] | null;
  /** Уже отформатированное значение для показа пользователю */
  display: string;
  status: DataStatus;
  /** Почему метрика важна — показывается подсказкой */
  hint?: string | null;
  source?: SourceKey | null;
}

export interface CategoryScore {
  key: CategoryKey;
  title: string;
  /** 0..100 или null, если данных нет */
  score: number | null;
  status: DataStatus;
  /** Номинальный вес категории в методике (0..1) */
  weight: number;
  /** Вес после исключения категорий без данных (0..1) */
  effective_weight: number;
  /** Доля сигналов категории, по которым реально были данные */
  signal_coverage: number;
  summary: string;
  strengths: string[];
  weaknesses: string[];
  no_data_reason?: string | null;
  metrics: MetricValue[];
}

export interface Evidence {
  label: string;
  value: string;
  url?: string | null;
}

export interface Recommendation {
  id: string;
  category: CategoryKey;
  priority: Priority;
  title: string;
  problem: string;
  why: string;
  action: string;
  evidence: Evidence[];
  /** Ожидаемый прирост итогового Repo Health Score в баллах */
  expected_gain: number;
  /** Формулировка эффекта из методики — показывается, когда числовой прирост не задан */
  impact?: string | null;
}

export interface CollectionError {
  category: string | null;
  source: string | null;
  code: string | null;
  message: string;
}

export interface CollectionInfo {
  collected_at: string;
  duration_ms: number | null;
  collector_version: string | null;
  sources_used: Record<SourceKey, boolean | null>;
  errors: CollectionError[];
}

export interface ScoreBlock {
  total: number | null;
  grade: string;
  /** Доля веса методики, покрытая данными (0..1) */
  coverage: number;
  formula_version: string;
  weights: Record<CategoryKey, number>;
}

export interface HistoryPoint {
  analyzed_at: string;
  total: number | null;
}

export interface RepoSummary {
  id: string;
  full_path: string;
  owner: string;
  name: string;
  url: string;
  description: string | null;
  primary_language: string | null;
  likes: number;
  last_activity_at: string | null;
  analyzed_at: string;
  total_score: number | null;
  grade: string;
  coverage: number;
  categories: Partial<Record<CategoryKey, number | null>>;
  no_data_categories: CategoryKey[];
  not_applicable_categories?: CategoryKey[];
  has_ci: boolean;
  security_status: DataStatus;
  rank: number | null;
  /** Изменение места в рейтинге с прошлого пересчёта (доп. возможность) */
  rank_delta?: number | null;
}

export interface RepoReport extends Omit<RepoSummary, 'total_score' | 'grade' | 'coverage' | 'categories' | 'rank'> {
  visibility: 'public' | 'private' | string;
  default_branch: string | null;
  likes_percentile: number | null;
  score: ScoreBlock;
  categories: CategoryScore[];
  recommendations: Recommendation[];
  strengths: { category: CategoryKey; text: string }[];
  risks: { category: CategoryKey; text: string }[];
  summary: string;
  collection: CollectionInfo;
  history: HistoryPoint[];
  rank?: number | null;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type SortKey = 'score' | 'likes' | 'activity' | 'name';

export interface RatingQuery {
  query?: string;
  language?: string | null;
  sort?: SortKey;
  order?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
  has_ci?: boolean | null;
  security_status?: DataStatus | null;
  min_coverage?: number | null;
}

export interface LanguageFacet {
  language: string;
  count: number;
}

export interface PlatformStats {
  repos_total: number;
  repos_scored: number;
  median_score: number | null;
  no_data_security: number;
  with_ci: number;
  last_run_at: string;
  next_run_at: string;
  /** cron-расписание периодического пересчёта */
  schedule: string;
  /** Веса категорий в действующей методике */
  weights?: Partial<Record<CategoryKey, number>>;
}

export interface User {
  id: string;
  login: string;
  display_name: string;
  email: string | null;
  avatar_url: string | null;
  provider: 'yandex_id' | string;
}

export interface OwnedRepo extends RepoSummary {
  role: string;
  visibility: string;
  last_analysis_at: string | null;
  /** true — список подобран сервисом: платформа не отдала репозитории пользователя */
  demo?: boolean;
  /** organization — репозиторий пользователя, accessible — просто доступный ему */
  source?: 'organization' | 'accessible';
}

export type AnalysisStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface AnalysisStage {
  key: string;
  title: string;
  status: 'pending' | 'running' | 'done' | 'skipped' | 'failed';
  detail?: string | null;
}

export interface Analysis {
  id: string;
  repo_full_path: string;
  status: AnalysisStatus;
  progress: number;
  stages: AnalysisStage[];
  started_at: string;
  finished_at: string | null;
  error: string | null;
  /** Итоговый отчёт появляется, когда status === 'succeeded' */
  report: RepoReport | null;
}
