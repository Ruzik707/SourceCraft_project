import { useState } from 'react';
import type { Recommendation } from '@/api/types';
import { Badge } from '@/components/ui';
import { CATEGORY_TITLE, PRIORITY_LABEL, PRIORITY_TONE } from '@/lib/score';

export function Recommendations({ items }: { items: Recommendation[] }) {
  const [onlyActionable, setOnlyActionable] = useState(false);
  const visible = onlyActionable ? items.filter((r) => r.priority !== 'info') : items;

  if (!items.length) {
    return <p className="text-muted">Критичных замечаний не найдено — сервис не нашёл проблем в собранных данных.</p>;
  }

  return (
    <div className="stack">
      <div className="row-wrap no-print" style={{ justifyContent: 'space-between' }}>
        <span className="text-muted">
          {items.length} рекомендаций, отсортированы по приоритету и ожидаемому эффекту на Score
        </span>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={onlyActionable}
            onChange={(e) => setOnlyActionable(e.target.checked)}
          />
          Скрыть информационные
        </label>
      </div>

      <div className="stack-sm">
        {visible.map((rec, i) => (
          <article key={rec.id} className={`rec rec--${rec.priority}`}>
            <header className="row-wrap" style={{ justifyContent: 'space-between' }}>
              <span className="row-wrap" style={{ gap: 8 }}>
                <Badge tone={PRIORITY_TONE[rec.priority]}>
                  <span className="dot" />
                  {PRIORITY_LABEL[rec.priority]} приоритет
                </Badge>
                <Badge tone="neutral">{CATEGORY_TITLE[rec.category]}</Badge>
              </span>
              <span className="text-subtle">#{i + 1}</span>
            </header>

            <h3>{rec.title}</h3>

            <dl className="rec__grid">
              <div className="rec__block">
                <dt>Обнаруженная проблема</dt>
                <dd>{rec.problem}</dd>
              </div>
              <div className="rec__block">
                <dt>Почему это важно</dt>
                <dd>{rec.why}</dd>
              </div>
              <div className="rec__block">
                <dt>Рекомендуемое действие</dt>
                <dd>{rec.action}</dd>
              </div>
              <div className="rec__block">
                <dt>Ожидаемое влияние на Score</dt>
                <dd>
                  {rec.expected_gain > 0 ? (
                    <strong style={{ color: 'var(--good)' }}>+{rec.expected_gain.toFixed(1)} балла</strong>
                  ) : rec.impact ? (
                    <span className="text-muted">{rec.impact}</span>
                  ) : (
                    <span className="text-muted">
                      не влияет на Score напрямую, но снижает риск сопровождения
                    </span>
                  )}
                </dd>
              </div>
            </dl>

            {rec.evidence.length ? (
              <div className="row-wrap" style={{ gap: 6 }}>
                <span className="field__label">На чём основан вывод:</span>
                {rec.evidence.map((e) => (
                  <span key={`${e.label}-${e.value}`} className="evidence">
                    {e.label}: <strong>{e.value}</strong>
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noreferrer" title="Открыть в SourceCraft">
                        ↗
                      </a>
                    ) : null}
                  </span>
                ))}
              </div>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
}
