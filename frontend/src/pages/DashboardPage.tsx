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
  const [platformToken, setPlatformToken] = useState('');
  const [savingToken, setSavingToken] = useState(false);
  const queryClient = useQueryClient();
  const runs = loadRuns().slice(0, 6);

  const items = (repos.data ?? []).filter((r) =>
    filter ? r.full_path.toLowerCase().includes(filter.toLowerCase()) : true,
  );

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
        <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
          <span className="text-muted">
            {repos.isLoading ? 'Загружаем список…' : `Доступно ${formatNumber(items.length)} репозиториев`}
          </span>
          <input
            className="input"
            placeholder="Фильтр по названию"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ maxWidth: 260 }}
          />
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
                  <Badge tone="neutral">{repo.role}</Badge>
                  {repo.primary_language ? <Badge tone="neutral">{repo.primary_language}</Badge> : null}
                </div>
                <span className="text-subtle">
                  {repo.description ?? 'без описания'}
                </span>
                <span className="text-subtle">
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
