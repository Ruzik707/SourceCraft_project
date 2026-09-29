import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { ApiError } from '@/api/client';
import { useAiRecommendations } from '@/api/hooks';
import type { RepoReport } from '@/api/types';
import { Badge, Banner, Card, Spinner } from '@/components/ui';
import { CategoryRadar } from '@/components/score/CategoryRadar';
import { ScoreGauge } from '@/components/score/ScoreGauge';
import { Sparkline } from '@/components/score/Sparkline';
import { CategoryCard } from './CategoryCard';
import { DataGaps } from './DataGaps';
import { Recommendations } from './Recommendations';
import { formatDateTime, formatNumber, formatPercent, formatScore, timeAgo } from '@/lib/format';
import { CATEGORY_TITLE, scoreColor } from '@/lib/score';

function aiErrorMessage(error: unknown): string {
  const err = error as ApiError;
  // Репозиторий уже на экране, значит 404 отдал не он, а отсутствующий эндпоинт
  if (err.status === 404 || err.status === 501) return 'Сервер пока не умеет генерировать рекомендации.';
  return err.userMessage ?? 'Не удалось получить ответ ИИ.';
}

export function ReportView({ report, actions }: { report: RepoReport; actions?: ReactNode }) {
  const scored = report.categories.filter((c) => c.score !== null);

  // Ответ ИИ относится только к тому репозиторию, для которого его запросили:
  // при переходе на другой отчёт снова показываются базовые рекомендации.
  const ai = useAiRecommendations();
  const aiForThis = ai.variables === report.full_path;
  const aiResult = aiForThis ? ai.data : undefined;
  const aiPending = aiForThis && ai.isPending;
  const aiError = aiForThis && ai.isError ? aiErrorMessage(ai.error) : null;

  const recommendations = aiResult?.recommendations ?? report.recommendations;
  const topRecs = recommendations.filter((r) => r.priority !== 'info').slice(0, 3);

  return (
    <div className="stack" style={{ gap: 'var(--space-6)' }}>
      {/* ─────────────── шапка отчёта ─────────────── */}
      <header className="stack-sm">
        <div className="row-wrap" style={{ justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div className="stack-sm" style={{ gap: 6 }}>
            <h1>
              <a href={report.url} target="_blank" rel="noreferrer">
                {report.full_path}
              </a>
            </h1>
            {report.description ? <p className="text-muted">{report.description}</p> : null}
            <div className="row-wrap" style={{ gap: 8 }}>
              {report.primary_language ? <Badge tone="neutral">{report.primary_language}</Badge> : null}
              <Badge tone="neutral">♥ {formatNumber(report.likes)}</Badge>
              <Badge tone="neutral">ветка {report.default_branch ?? '—'}</Badge>
              {report.visibility === 'private' ? <Badge tone="warn">приватный</Badge> : null}
              <span className="text-subtle">
                последняя активность: {timeAgo(report.last_activity_at)}
              </span>
            </div>
          </div>
          <div className="row-wrap no-print">{actions}</div>
        </div>
        <p className="text-subtle">
          Анализ выполнен {formatDateTime(report.analyzed_at)} · методика {report.score.formula_version}
        </p>
      </header>

      {/* ─────────────── итог и радар ─────────────── */}
      <Card>
        <div className="hero">
          <ScoreGauge score={report.score.total} grade={report.score.grade} coverage={report.score.coverage} />

          <div className="stack">
            <p style={{ fontSize: 16 }}>{report.summary}</p>

            <div className="grid-2">
              <div className="stack-sm">
                <span className="field__label">Сильные стороны</span>
                {report.strengths.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {report.strengths.slice(0, 5).map((s, i) => (
                      <li key={i}>
                        <span className="text-muted">{CATEGORY_TITLE[s.category]}:</span> {s.text}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-subtle">Выраженных сильных сторон в собранных данных не найдено.</p>
                )}
              </div>
              <div className="stack-sm">
                <span className="field__label">Проблемы, требующие внимания</span>
                {report.risks.length ? (
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {report.risks.slice(0, 5).map((s, i) => (
                      <li key={i}>
                        <span className="text-muted">{CATEGORY_TITLE[s.category]}:</span> {s.text}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-subtle">Проблем в собранных данных не обнаружено.</p>
                )}
              </div>
            </div>

            {topRecs.length ? (
              <div className="row-wrap" style={{ gap: 8 }}>
                <span className="field__label">Что сделать в первую очередь:</span>
                {topRecs.map((r) => (
                  <a key={r.id} href="#recommendations" className="badge">
                    {r.title}
                    {r.expected_gain > 0 ? ` +${r.expected_gain.toFixed(1)}` : ''}
                  </a>
                ))}
              </div>
            ) : null}

            <div className="row-wrap no-print">
              {aiResult ? (
                <>
                  <a href="#recommendations" className="btn btn--sm">
                    ✦ К рекомендациям ИИ
                  </a>
                  <button type="button" className="btn btn--sm btn--ghost" onClick={() => ai.reset()}>
                    Вернуть базовые
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="btn btn--sm btn--primary"
                  disabled={aiPending}
                  onClick={() => ai.mutate(report.full_path)}
                >
                  ✦ Сгенерировать рекомендации при помощи ИИ
                </button>
              )}
              {aiPending ? <Spinner label="ИИ готовит рекомендации…" /> : null}
            </div>
            {aiError ? (
              <Banner tone="warn" icon="!">
                {aiError} Показаны базовые рекомендации.
              </Banner>
            ) : null}
          </div>
        </div>
      </Card>

      {/* ─────────────── категории ─────────────── */}
      <section className="stack" id="categories">
        <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
          <h2>Оценки по категориям</h2>
          <span className="text-subtle">
            {scored.length} из {report.categories.length} категорий с данными
          </span>
        </div>

        <div className="grid-2">
          <Card className="card--flat">
            <div style={{ display: 'grid', placeItems: 'center' }}>
              <CategoryRadar categories={report.categories} />
            </div>
          </Card>

          <Card className="card--flat">
            <div className="card__title">
              <h3>Как получилась оценка</h3>
            </div>
            <p className="text-muted" style={{ fontSize: 13.5, marginBottom: 12 }}>
              Repo Health Score = Σ (оценка категории × вес) ÷ Σ (вес категорий с данными). Категории
              без данных не входят ни в числитель, ни в знаменатель.
            </p>
            <div className="table-wrap" style={{ border: 'none' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Категория</th>
                    <th>Оценка</th>
                    <th>Вес</th>
                    <th>Вклад</th>
                  </tr>
                </thead>
                <tbody>
                  {report.categories.map((c) => (
                    <tr key={c.key}>
                      <td>{c.title}</td>
                      <td style={{ color: scoreColor(c.score), fontWeight: 650 }}>
                        {c.score === null ? 'нет данных' : formatScore(c.score)}
                      </td>
                      <td className="text-muted">{formatPercent(c.weight)}</td>
                      <td>
                        {c.score === null ? (
                          <span className="text-subtle">исключена</span>
                        ) : (
                          <strong>{(c.score * c.effective_weight).toFixed(1)}</strong>
                        )}
                      </td>
                    </tr>
                  ))}
                  <tr>
                    <td colSpan={3}>
                      <strong>Repo Health Score</strong>
                    </td>
                    <td>
                      <strong style={{ color: scoreColor(report.score.total) }}>
                        {formatScore(report.score.total)}
                      </strong>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="text-subtle" style={{ marginTop: 10 }}>
              <Link to="/methodology">Полное описание методики и правил нормализации →</Link>
            </p>
          </Card>
        </div>

        <div className="grid-2">
          {report.categories.map((c) => (
            <CategoryCard key={c.key} category={c} />
          ))}
        </div>
      </section>

      {/* ─────────────── рекомендации ─────────────── */}
      <section className="stack" id="recommendations">
        <h2>Приоритизированные рекомендации</h2>

        {aiResult ? (
          <Banner icon="✦">
            {aiResult.model
              ? `Рекомендации сгенерированы ИИ (${aiResult.model}) по фактам этого отчёта — проверьте их, прежде чем применять.`
              : 'Демо-режим: модель не вызывалась, показаны базовые рекомендации в том виде, в каком их вернёт ИИ.'}
          </Banner>
        ) : null}
        <div aria-busy={aiPending} style={aiPending ? { opacity: 0.5, pointerEvents: 'none' } : undefined}>
          <Recommendations items={recommendations} />
        </div>
      </section>

      {/* ─────────────── данные ─────────────── */}
      <section className="stack" id="data">
        <h2>Полнота данных</h2>
        <Card className="card--flat">
          <DataGaps report={report} />
        </Card>
      </section>

      {/* ─────────────── история ─────────────── */}
      <section className="stack" id="history">
        <h2>История оценки</h2>
        <Card className="card--flat">
          {report.history && report.history.length > 1 ? (
            <div className="stack-sm">
              <Sparkline points={report.history} />
              <span className="text-subtle">
                {report.history.length} замеров, последний — {formatDateTime(report.analyzed_at)}
              </span>
            </div>
          ) : (
            <p className="text-muted">
              Пока только один замер ({formatDateTime(report.analyzed_at)}). Динамика появится после
              следующего планового пересчёта — сервис пересчитывает открытые репозитории по расписанию.
            </p>
          )}
        </Card>
      </section>
    </div>
  );
}
