import { useStats } from '@/api/hooks';
import type { CategoryKey } from '@/api/types';
import { Card } from '@/components/ui';
import { CATEGORY_HINT, CATEGORY_ORDER, CATEGORY_TITLE } from '@/lib/score';

/** Веса подобраны Optuna; сервис отдаёт актуальные значения в GET /stats. */
const FALLBACK_WEIGHTS: Record<CategoryKey, number> = {
  security: 0.198,
  code_health: 0.298,
  activity: 0.108,
  documentation: 0.1,
  cicd: 0.102,
  issues: 0.191,
};

export function MethodologyPage() {
  const stats = useStats();
  const weights = stats.data?.weights ?? FALLBACK_WEIGHTS;

  return (
    <div className="stack" style={{ gap: 'var(--space-6)', maxWidth: 900 }}>
      <header className="stack-sm">
        <h1>Методика расчёта Repo Health Score</h1>
        <p className="text-muted">
          Оценка объяснимая и воспроизводимая: каждая цифра на странице анализа раскрывается до
          конкретной метрики и источника данных.
        </p>
      </header>

      <Card>
        <div className="stack-sm">
          <h2>Формула</h2>
          <pre
            className="mono"
            style={{
              background: 'var(--surface-2)',
              padding: 'var(--space-4)',
              borderRadius: 'var(--radius-md)',
              overflowX: 'auto',
              border: '1px solid var(--border)',
            }}
          >
{`Score = Σ (score_категории × вес_категории)
        ─────────────────────────────────
        Σ (вес_категорий, по которым есть данные)

score_категории ∈ [0; 100]  — сумма баллов её метрик
вес_категории               — доля категории в методике
`}
          </pre>
          <p className="text-muted">
            Категории без данных не попадают ни в числитель, ни в знаменатель: репозиторий не получает
            за них ни баллов, ни штрафа. Рядом со Score всегда показана «полнота данных» — какая доля
            веса методики реально подтверждена фактами.
          </p>
        </div>
      </Card>

      <Card>
        <div className="stack-sm">
          <h2>Категории и веса</h2>
          <p className="text-muted">
            Веса подобраны на исторической выборке и приходят из сервиса. В каждом отчёте рядом с
            ними показан эффективный вес: он пересчитывается, когда часть категорий остаётся без
            данных.
          </p>
          <div className="table-wrap" style={{ border: 'none' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Категория</th>
                  <th>Вес</th>
                  <th>Что учитывается</th>
                </tr>
              </thead>
              <tbody>
                {CATEGORY_ORDER.map((key) => (
                  <tr key={key}>
                    <td>
                      <strong>{CATEGORY_TITLE[key]}</strong>
                    </td>
                    <td>{((weights[key] ?? 0) * 100).toFixed(1)}%</td>
                    <td className="text-muted" style={{ fontSize: 13.5 }}>
                      {CATEGORY_HINT[key]}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      <Card>
        <div className="stack-sm">
          <h2>Статусы данных</h2>
          <p className="text-muted">
            Отсутствие данных и плохой результат — разные вещи, и в интерфейсе они выглядят по-разному.
          </p>
          <ul style={{ margin: 0, paddingLeft: 18 }} className="stack-sm">
            <li>
              <strong>Данные собраны</strong> — источник ответил, метрики категории посчитаны полностью.
            </li>
            <li>
              <strong>Часть данных недоступна</strong> — категория оценена по доступным сигналам,
              рядом показана доля покрытия. Пример: конфигурация CI прочитана из репозитория, а
              история прогонов закрыта правами.
            </li>
            <li>
              <strong>Нет данных</strong> — источник недоступен (например, AppSec отвечает 403 для
              анонимного сборщика). Категория исключается из Score, а не обнуляется.
            </li>
            <li>
              <strong>Не применимо</strong> — сущности просто нет: трекер задач не используется или в
              репозитории слишком мало кода для оценки техдолга.
            </li>
          </ul>
        </div>
      </Card>

      <Card>
        <div className="stack-sm">
          <h2>Устойчивость к накрутке</h2>
          <ul style={{ margin: 0, paddingLeft: 18 }} className="stack-sm">
            <li>Лайки не входят в Score: они показаны отдельной колонкой рейтинга.</li>
            <li>
              Активность считается не по числу коммитов, а по совокупности: свежесть, объём за 90 дней,
              число контрибьюторов и распределение работы между ними. Серия пустых коммитов одного
              автора почти не двигает оценку.
            </li>
            <li>
              Метрики нормализованы по размеру проекта (например, TODO на 1000 строк), поэтому крупный
              репозиторий не штрафуется за объём.
            </li>
            <li>
              Ни одна отдельная метрика не может изменить итоговый Score больше, чем на вес своей
              категории.
            </li>
          </ul>
        </div>
      </Card>

      <Card>
        <div className="stack-sm">
          <h2>Как формируются рекомендации</h2>
          <p className="text-muted">
            Каждая рекомендация — это правило над собранными фактами. У неё есть проблема, объяснение
            важности, доказательства, конкретное действие и ожидаемый прирост Score.
          </p>
          <p className="text-muted">
            Ожидаемый прирост считается по той же формуле, что и сама оценка: баллы, которые вернёт
            исправление внутри категории, умножаются на эффективный вес категории. Если действие не
            влияет на Score напрямую, это честно указано в карточке.
          </p>
          <p className="text-muted">
            Рекомендации сортируются по приоритету (критический → высокий → средний → низкий), внутри
            приоритета — по ожидаемому эффекту.
          </p>
        </div>
      </Card>

      <Card>
        <div className="stack-sm">
          <h2>Периодический пересчёт</h2>
          <p className="text-muted">
            Открытые репозитории пересчитываются по расписанию: сервис заново собирает данные,
            пересчитывает Score и фиксирует статус и время последнего анализа. Владелец репозитория
            может запустить анализ вручную из личного кабинета — например, сразу после исправлений.
          </p>
        </div>
      </Card>
    </div>
  );
}
