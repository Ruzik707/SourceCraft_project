import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './index';
import type { Analysis, RatingQuery } from './types';

export const queryKeys = {
  rating: (q: RatingQuery) => ['rating', q] as const,
  repo: (owner: string, name: string) => ['repo', owner, name] as const,
  languages: ['languages'] as const,
  stats: ['stats'] as const,
  me: ['me'] as const,
  myRepos: ['me', 'repos'] as const,
  analysis: (id: string) => ['analysis', id] as const,
};

export function useRating(q: RatingQuery) {
  return useQuery({
    queryKey: queryKeys.rating(q),
    queryFn: () => api.getRating(q),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });
}

export function useRepoReport(owner?: string, name?: string) {
  return useQuery({
    queryKey: queryKeys.repo(owner ?? '', name ?? ''),
    queryFn: () => api.getRepo(owner!, name!),
    enabled: Boolean(owner && name),
    staleTime: 60_000,
    retry: (count, error) => {
      const status = (error as { status?: number }).status;
      if (status === 404 || status === 403) return false;
      return count < 2;
    },
  });
}

export function useLanguages() {
  return useQuery({ queryKey: queryKeys.languages, queryFn: api.getLanguages, staleTime: 600_000 });
}

export function useStats() {
  return useQuery({ queryKey: queryKeys.stats, queryFn: api.getStats, staleTime: 300_000 });
}

export function useMyRepos(enabled: boolean) {
  return useQuery({ queryKey: queryKeys.myRepos, queryFn: api.getMyRepos, enabled, staleTime: 60_000 });
}

/** Запуск анализа; дальше за статусом следит useAnalysis c поллингом. */
export function useStartAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fullPath: string) => api.startAnalysis(fullPath),
    onSuccess: (analysis) => {
      qc.setQueryData(queryKeys.analysis(analysis.id), analysis);
    },
  });
}

export function useAnalysis(id: string | null) {
  return useQuery({
    queryKey: queryKeys.analysis(id ?? ''),
    queryFn: () => api.getAnalysis(id!),
    enabled: Boolean(id),
    // 404 означает, что запуска нет: например, ссылка осталась от прошлой сессии.
    // Повторять такой запрос бессмысленно.
    retry: (count, error) => (error as { status?: number }).status === 404 ? false : count < 2,
    refetchInterval: (query) => {
      if (query.state.status === 'error') return false;
      const data = query.state.data as Analysis | undefined;
      if (!data) return 1000;
      return data.status === 'queued' || data.status === 'running' ? 1000 : false;
    },
  });
}
