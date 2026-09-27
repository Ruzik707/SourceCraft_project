import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { ApiError } from '@/api';
import { useAnalysis, useStartAnalysis } from '@/api/hooks';
import { Badge, Banner, Card, Progress, Toast, useToast } from '@/components/ui';
import { ExportMenu } from '@/components/report/ExportMenu';
import { ReportView } from '@/components/report/ReportView';
import { formatDateTime, formatScore } from '@/lib/format';
import { lastRunFor, saveRun, type RunRecord } from '@/lib/runHistory';

const STAGE_ICON: Record<string, string> = {
  done: '✓',
  running: '•',
  pending: '·',
  skipped: '–',
  failed: '✕',
};

/**
 * Экран запуска анализа собственного репозитория: первичный запуск, прогресс по
 * стадиям сбора, результат и повторный запуск с дельтой к прошлому прогону.
 */
export function AnalysisPage() {
  const { owner, name } = useParams<{ owner: string; name: string }>();
  const fullPath = `${owner}/${name}`;
  const [params, setParams] = useSearchParams();
  const [toast, showToast] = useToast();

  const [analysisId, setAnalysisId] = useState<string | null>(params.get('run'));
  const start = useStartAnalysis();
  const analysis = useAnalysis(analysisId);
  const autoStarted = useRef(false);

  /** Прошлый успешный прогон этого репозитория — для дельты Score. */
  const previous = useMemo<RunRecord | undefined>(
    () => lastRunFor(fullPath, analysisId ?? undefined),
    [fullPath, analysisId],
  );

  const run = () => {
    start.mutate(fullPath, {
      onSuccess: (a) => {
        setAnalysisId(a.id);
        const next = new URLSearchParams(params);
        next.set('run', a.id);
        setParams(next, { replace: true });
        saveRun({
          full_path: fullPath,
          analysis_id: a.id,
          started_at: a.started_at,
          finished_at: null,
          status: a.status,
          total: null,
        });
      },
    });
  };

  // первый заход на страницу без ?run= — запускаем анализ сразу
  useEffect(() => {
    if (!analysisId && !autoStarted.current) {
      autoStarted.current = true;
      run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // сохраняем результат в историю запусков
  const saved = useRef<string | null>(null);
  useEffect(() => {
    const data = analysis.data;
    if (!data || data.status === 'queued' || data.status === 'running') return;
    if (saved.current === data.id) return;
    saved.current = data.id;
    saveRun({
      full_path: fullPath,
      analysis_id: data.id,
      started_at: data.started_at,
      finished_at: data.finished_at,
      status: data.status,
      total: data.report?.score.total ?? null,
    });
  }, [analysis.data, fullPath]);

  const data = analysis.data;
  const inProgress = !analysis.isError && (!data || data.status === 'queued' || data.status === 'running');
  const delta =
    data?.report?.score.total != null && previous?.total != null
      ? data.report.score.total - previous.total
      : null;

  return (
    <>
      <div className="stack" style={{ gap: 'var(--space-6)' }}>
        {start.isError ? (
          <Banner tone="warn" icon="⚠">
            {(start.error as ApiError)?.userMessage ?? 'Не удалось запустить анализ.'}{' '}
            <button type="button" className="btn btn--sm" onClick={run}>
              Повторить
            </button>
          </Banner>
        ) : null}

        {inProgress ? (
          <Card>
            <div className="stack">
              <div className="stack-sm">
                <h1>Анализируем {fullPath}</h1>
                <p className="text-muted">
                  Сервис собирает данные через API и CLI SourceCraft. Страницу можно не держать
                  открытой — результат сохранится в истории запусков.
                </p>
              </div>

              <Progress
                value={data?.progress ?? 5}
                label={`${data?.progress ?? 0}% · запуск ${
                  data ? formatDateTime(data.started_at) : 'создаётся'
                }`}
              />

              <div className="stage-list">
                {(data?.stages ?? []).map((stage) => (
                  <div key={stage.key} className={`stage stage--${stage.status}`}>
                    <span className="stage__icon" aria-hidden>
                      {STAGE_ICON[stage.status] ?? '·'}
                    </span>
                    <span className="stack-sm" style={{ gap: 0 }}>
                      <span style={{ fontWeight: stage.status === 'running' ? 650 : 500 }}>
                        {stage.title}
                      </span>
                      {stage.detail ? <span className="text-subtle">{stage.detail}</span> : null}
                    </span>
                    <span className="spacer" />
                    {stage.status === 'skipped' ? <Badge tone="nodata">нет доступа</Badge> : null}
                    {stage.status === 'running' ? <Badge tone="info">выполняется</Badge> : null}
                  </div>
                ))}
              </div>
            </div>
          </Card>
        ) : null}

        {analysis.isError ? (
          <Banner tone="warn" icon="⚠">
            Этот запуск анализа не найден на сервере — скорее всего ссылка осталась от
            прошлой сессии.{' '}
            <button type="button" className="btn btn--sm" onClick={run}>
              Запустить заново
            </button>
          </Banner>
        ) : null}

        {data?.status === 'failed' ? (
          <Banner tone="warn" icon="⚠">
            Анализ завершился с ошибкой: {data.error ?? 'причина не передана'}.{' '}
            <button type="button" className="btn btn--sm" onClick={run}>
              Запустить снова
            </button>
          </Banner>
        ) : null}

        {data?.status === 'succeeded' && data.report ? (
          <>
            {delta !== null ? (
              <Banner tone={delta < 0 ? 'warn' : 'info'} icon={delta > 0 ? '↑' : delta < 0 ? '↓' : '='}>
                Повторный анализ:{' '}
                {Math.abs(delta) < 0.05 ? (
                  <>
                    Score не изменился — по-прежнему{' '}
                    <strong>{formatScore(data.report.score.total)}</strong>. С прошлого прогона
                    собранные данные остались теми же.
                  </>
                ) : (
                  <>
                    Score {delta > 0 ? 'вырос' : 'снизился'} на{' '}
                    <strong>{Math.abs(delta).toFixed(1)}</strong> балла относительно прошлого прогона
                    ({formatScore(previous?.total ?? null)} → {formatScore(data.report.score.total)}).
                  </>
                )}
              </Banner>
            ) : (
              <Banner icon="✓">
                Анализ завершён {formatDateTime(data.finished_at)}. Запустите его повторно после
                исправлений — сервис покажет разницу.
              </Banner>
            )}

            <ReportView
              report={data.report}
              actions={
                <>
                  <button type="button" className="btn" onClick={run} disabled={start.isPending}>
                    {start.isPending ? 'Запускаем…' : 'Запустить повторно'}
                  </button>
                  <ExportMenu report={data.report} onDone={showToast} />
                </>
              }
            />
          </>
        ) : null}
      </div>
      <Toast message={toast} />
    </>
  );
}
