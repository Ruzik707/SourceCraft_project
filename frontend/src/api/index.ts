/**
 * Фасад API. Один переключатель VITE_DATA_SOURCE решает, идти ли в реальный
 * бэкенд или в мок-снимок: остальной код приложения об этом не знает.
 */
import { API_BASE_URL, buildQuery, request, setToken } from './client';
import { mockApi } from './mock';
import type {
  Analysis,
  LanguageFacet,
  OwnedRepo,
  Paged,
  PlatformStats,
  RatingQuery,
  RepoReport,
  RepoSummary,
  User,
} from './types';

export const DATA_SOURCE: 'mock' | 'api' =
  (import.meta.env.VITE_DATA_SOURCE as 'mock' | 'api') ?? 'mock';

export const IS_MOCK = DATA_SOURCE === 'mock';

/**
 * Авторизация и личный кабинет могут оставаться на моках, пока бэкенд не поднял
 * Я ID и очередь анализа: публичная часть при этом уже работает на боевых данных.
 */
export const AUTH_SOURCE: 'mock' | 'api' =
  (import.meta.env.VITE_AUTH_SOURCE as 'mock' | 'api') ?? DATA_SOURCE;

export const IS_AUTH_MOCK = AUTH_SOURCE === 'mock';

export const api = {
  getRating(q: RatingQuery): Promise<Paged<RepoSummary>> {
    if (IS_MOCK) return mockApi.getRating(q);
    return request<Paged<RepoSummary>>(`/repos${buildQuery({ ...q })}`);
  },

  getRepo(owner: string, name: string): Promise<RepoReport> {
    if (IS_MOCK) return mockApi.getRepo(owner, name);
    return request<RepoReport>(`/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`);
  },

  getLanguages(): Promise<LanguageFacet[]> {
    if (IS_MOCK) return mockApi.getLanguages();
    return request<LanguageFacet[]>('/languages');
  },

  getStats(): Promise<PlatformStats> {
    if (IS_MOCK) return mockApi.getStats();
    return request<PlatformStats>('/stats');
  },

  getMe(): Promise<User> {
    if (IS_AUTH_MOCK) return mockApi.getMe();
    return request<User>('/me');
  },

  getMyRepos(): Promise<OwnedRepo[]> {
    if (IS_AUTH_MOCK) return mockApi.getMyRepos();
    return request<OwnedRepo[]>('/me/repos');
  },

  startAnalysis(fullPath: string): Promise<Analysis> {
    if (IS_AUTH_MOCK) return mockApi.startAnalysis(fullPath);
    return request<Analysis>('/analyses', {
      method: 'POST',
      body: JSON.stringify({ repo_full_path: fullPath }),
    });
  },

  getAnalysis(id: string): Promise<Analysis> {
    if (IS_AUTH_MOCK) return mockApi.getAnalysis(id);
    return request<Analysis>(`/analyses/${encodeURIComponent(id)}`);
  },

  /** Личный токен доступа SourceCraft: с ним сервис видит репозитории пользователя. */
  setSourceCraftToken(token: string): Promise<void> {
    if (IS_AUTH_MOCK) return Promise.resolve();
    return request<void>('/me/sourcecraft-token', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  },

  logout(): Promise<void> {
    setToken(null);
    if (IS_MOCK) return Promise.resolve();
    return request<void>('/auth/logout', { method: 'POST' }).catch(() => undefined);
  },

  /** URL, на который уводим пользователя для входа через Я ID. */
  /**
   * Ссылка входа. redirect_uri идёт без параметров: в приложении Яндекс OAuth
   * зарегистрирован точный адрес, а куда вести дальше — отдельный параметр next.
   */
  loginUrl(redirectPath: string): string {
    const redirectUri = `${window.location.origin}/auth/callback`;
    return `${API_BASE_URL}/auth/yandex/login${buildQuery({
      redirect_uri: redirectUri,
      next: redirectPath,
    })}`;
  },

  /** Доступна ли живая авторизация или личный кабинет работает на демо-данных. */
  authIsLive(): boolean {
    return !IS_AUTH_MOCK;
  },

  /** Ссылка на серверную выгрузку отчёта (бэк умеет отдавать .md и .pdf). */
  reportUrl(fullPath: string, format: 'md' | 'pdf'): string {
    return `${API_BASE_URL}/repos/${fullPath}/report.${format}`;
  },

  /** Badge для README (доп. возможность). */
  badgeUrl(fullPath: string): string {
    const base = IS_MOCK ? '' : API_BASE_URL;
    return `${window.location.origin}${base}/badge/${fullPath}.svg`;
  },
};

export * from './types';
export { ApiError, getToken, setToken } from './client';
