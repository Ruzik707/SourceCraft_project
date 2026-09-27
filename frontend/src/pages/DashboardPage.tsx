import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, IS_AUTH_MOCK, api } from '@/api';
import { queryKeys, useMyRepos } from '@/api/hooks';
import { useAuth } from '@/auth/AuthProvider';
import { Badge, Banner, Card, EmptyState, Skeleton } from '@/components/ui';
import { CoverageMeter, ScorePill } from '@/components/score/ScoreBits';
import { formatDateTime, formatNumber, timeAgo } from '@/lib/format';
import { loadRuns } from '@/lib/runHistory';

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const repos = useMyRepos(true);
  const [filter, setFilter] = useState('');
  const [org, setOrg] = useState<string>('all');
  const [sort, setSort] = useState<'default' | 'score' | 'name'>('default');
  const [hideEmpty, setHideEmpty] = useState(true);
  const [platformToken, setPlatformToken] = useState('');
  const [savingToken, setSavingToken] = useState(false);
  const queryClient = useQueryClient();
  const runs = loadRuns().slice(0, 6);

  const all = repos.data ?? [];

  // Организации собираем из самого списка: их состав приходит с платформы
  const organizations = Array.from(
    all.reduce((acc, r) => {
      const slug = r.owner ?? '—';
      const entry = acc.get(slug) ?? { slug, label: r.organization_name ?? slug, count: 0 };
      entry.count += 1;
      acc.set(slug, entry);
      return acc;
    }, new Map<string, { slug: string; label: string; count: number }>()).values(),
  ).sort((a, b) => b.count - a.count);

  const emptyCount = all.filter((r) => r.is_empty).length;

  const items = all
    .filter((r) => {
      if (org !== 'all' && r.owner !== org) return false;
      if (hideEmpty && r.is_empty) return false;
      return filter ? r.full_path.toLowerCase().includes(filter.toLowerCase()) : true;
    })
    .sort((a, b) => {
      if (sort === 'score') return (b.total_score ?? -1) - (a.total_score ?? -1);
      if (sort === 'name') return a.full_path.localeCompare(b.full_path);
      return 0; // порядок с сервера: личная организация первой
    });

  return (
    <div className="stack" style={{ gap: 'var(--space-6)' }}>
      <header className="stack-sm">
        <h1>Мои репозитории</h1>
        <p className="text-muted" style={{ maxWidth: 760 }}>
          Вы вошли как <strong>{user?.display_name}</strong>
          {user?.email ? ` (${user.email})` : ''}. Сервис показывает репозитории, доступные вам в
          SourceCraft, и обращается к платформе от вашего имени: категории, закрытые правами доступа
          для анонимного сборщика, здесь заполняются.
        </p>
      </header>

      {repos.isError ? (
        <Banner tone="warn" icon="⚠">
          {(repos.error as ApiError)?.userMessage ?? 'Не удалось получить список репозиториев.'}{' '}
          <button type="button" className="btn btn--sm" onClick={() => repos.refetch()}>
            Повторить
          </button>
        </Banner>
      ) : null}

      {!IS_AUTH_MOCK && items.some((r) => r.demo) ? (
        <Banner icon="ⓘ">
          <div className="stack-sm">
            <span>
              Список подобран сервисом: платформа пока не отдала ваши репозитории по токену
              Я&nbsp;ID. Добавьте личный токен доступа SourceCraft — он создаётся в профиле
              платформы, хранится только в текущей сессии и удаляется при выходе.
            </span>
            <form
              className="row-wrap"
              onSubmit={(e) => {
                e.preventDefault();
                if (!platformToken.trim()) return;
                setSavingToken(true);
                void api
                  .setSourceCraftToken(platformToken.trim())
                  .then(() => {
                    setPlatformToken('');
                    return queryClient.invalidateQueries({ queryKey: queryKeys.myRepos });
                  })
                  .finally(() => setSavingToken(false));
              }}
            >
              <input
                className="input"
                type="password"
                placeholder="Личный токен доступа SourceCraft"
                value={platformToken}
                onChange={(e) => setPlatformToken(e.target.value)}
                style={{ minWidth: 280 }}
              />
              <button type="submit" className="btn" disabled={savingToken || !platformToken.trim()}>
                {savingToken ? 'Сохраняем…' : 'Подключить'}
              </button>
            </form>
          </div>
        </Banner>
      ) : null}

      {runs.length ? (
        <Card className="card--pad-sm">
          <div className="stack-sm">
            <span className="field__label">Последние запуски анализа</span>
            <div className="row-wrap" style={{ gap: 8 }}>
              {runs.map((r) => (
                <Link
                  key={r.analysis_id}
                  to={`/dashboard/analyze/${r.full_path}?run=${r.analysis_id}`}
                  className="badge"
                  title={formatDateTime(r.started_at)}
                >
                  {r.full_path} · {r.total !== null ? Math.round(r.total) : r.status} · {timeAgo(r.started_at)}
                </Link>
              ))}
            </div>
          </div>
        </Card>
      ) : null}

      <div className="stack-sm">
        <div className="row-wrap" style={{ justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <span className="text-muted">
            {repos.isLoading
              ? 'Загружаем список…'
              : `Показано ${formatNumber(items.length)} из ${formatNumber(all.length)}`}
          </span>

          <div className="row-wrap" style={{ gap: 'var(--space-3)' }}>
            {organizations.length > 1 ? (
              <div className="field">
                <label className="field__label" htmlFor="org">
                  Организация
                </label>
                <select
                  id="org"
                  className="select"
                  value={org}
                  onChange={(e) => setOrg(e.target.value)}
                >
                  <option value="all">Все ({all.length})</option>
                  {organizations.map((o) => (
                    <option key={o.slug} value={o.slug}>
                      {o.label} ({o.count})
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <div className="field">
              <label className="field__label" htmlFor="dash-sort">
                Сортировка
              </label>
              <select
                id="dash-sort"
                className="select"
                value={sort}
                onChange={(e) => setSort(e.target.value as typeof sort)}
              >
                <option value="default">Сначала личные</option>
                <option value="score">По Repo Health Score</option>
                <option value="name">По названию</option>
              </select>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="dash-filter">
                Поиск
              </label>
              <input
                id="dash-filter"
                className="input"
                placeholder="Фильтр по названию"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                style={{ maxWidth: 240 }}
              />
            </div>

            {emptyCount > 0 ? (
              <label className="checkbox" style={{ marginBottom: 8 }}>
                <input
                  type="checkbox"
                  checked={hideEmpty}
                  onChange={(e) => setHideEmpty(e.target.checked)}
                />
                Скрыть пустые ({emptyCount})
              </label>
            ) : null}
          </div>
        </div>

        {repos.isLoading ? (
          <div className="stack-sm">
            <Skeleton height={76} />
            <Skeleton height={76} />
            <Skeleton height={76} />
          </div>
        ) : null}

        {!repos.isLoading && !items.length ? (
          <EmptyState
            title="Репозитории не найдены"
            description="В вашем аккаунте SourceCraft нет репозиториев, доступных сервису, либо фильтр слишком узкий."
          />
        ) : null}

        <div className="stack-sm">
          {items.map((repo) => (
            <div key={repo.full_path} className="repo-list-item">
              <div className="stack-sm" style={{ gap: 6 }}>
                <div className="row-wrap" style={{ gap: 8 }}>
                  <Link to={`/repo/${repo.full_path}`} style={{ fontWeight: 650, fontSize: 15 }}>
                    {repo.full_path}
                  </Link>
                  <Badge tone={repo.visibility === 'private' ? 'warn' : 'neutral'}>
                    {repo.visibility === 'private' ? 'приватный' : 'публичный'}
                  </Badge>
                  {repo.role ? <Badge tone="neutral">{repo.role}</Badge> : null}
                  {repo.is_empty ? (
                    <Badge tone="warn" title="В репозитории нет кода — анализировать нечего">
                      пустой
                    </Badge>
                  ) : null}
                  {repo.source === 'accessible' ? (
                    <Badge tone="warn" title="Репозиторий не ваш: платформа отдала его как доступный или недавно открытый">
                      доступный
                    </Badge>
                  ) : null}
                  {repo.primary_language ? <Badge tone="neutral">{repo.primary_language}</Badge> : null}
                </div>
                <span className="text-subtle">
                  {repo.description ?? 'без описания'}
                </span>
                <span className="text-subtle">
                  {repo.organization_name ? `${repo.organization_name} · ` : ''}
                  Последний анализ:{' '}
                  {repo.last_analysis_at ? formatDateTime(repo.last_analysis_at) : 'не выполнялся'}
                </span>
              </div>

              <div className="row" style={{ gap: 'var(--space-4)' }}>
                <div className="stack-sm" style={{ gap: 4, alignItems: 'flex-end' }}>
                  <ScorePill score={repo.total_score} />
                  <CoverageMeter coverage={repo.coverage} />
                </div>
                <button
                  type="button"
                  className="btn"
                  disabled={repo.is_empty}
                  title={repo.is_empty ? 'В репозитории нет кода' : undefined}
                  onClick={() => navigate(`/dashboard/analyze/${repo.full_path}`)}
                >
                  {repo.last_analysis_at ? 'Пересчитать' : 'Анализировать'}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
