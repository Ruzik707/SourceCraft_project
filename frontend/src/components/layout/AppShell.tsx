import { useEffect, useState } from 'react';
import { Link, NavLink, Outlet, useLocation, useParams } from 'react-router-dom';
import { IS_AUTH_MOCK, IS_MOCK } from '@/api';
import { useAuth } from '@/auth/AuthProvider';
import { applyTheme, getStoredTheme, type Theme } from '@/lib/theme';
import { Dropdown } from '@/components/ui';

/** Хлебные крошки собираются из маршрута — как в навигации SourceCraft. */
function Breadcrumbs() {
  const { pathname } = useLocation();
  const params = useParams();
  const repo = params.owner && params.name ? `${params.owner}/${params.name}` : null;

  const parts: { label: string; to?: string }[] = [];
  if (pathname === '/') parts.push({ label: 'Рейтинг репозиториев' });
  else if (pathname.startsWith('/repo/')) {
    parts.push({ label: 'Рейтинг', to: '/' }, { label: repo ?? 'Репозиторий' });
  } else if (pathname.startsWith('/compare')) parts.push({ label: 'Сравнение проектов' });
  else if (pathname.startsWith('/methodology')) parts.push({ label: 'Методика расчёта' });
  else if (pathname.startsWith('/dashboard/analyze')) {
    parts.push({ label: 'Мои репозитории', to: '/dashboard' }, { label: repo ?? '' }, { label: 'Анализ' });
  } else if (pathname.startsWith('/dashboard')) parts.push({ label: 'Мои репозитории' });
  else if (pathname.startsWith('/login') || pathname.startsWith('/auth')) parts.push({ label: 'Вход через Я ID' });
  else parts.push({ label: 'Страница не найдена' });

  return (
    <nav className="crumbs" aria-label="Хлебные крошки">
      <Link to="/" title="На главную" aria-label="На главную">
        ⌂
      </Link>
      {parts.map((p, i) => (
        <span key={i} className="row" style={{ gap: 8, minWidth: 0 }}>
          <span className="crumbs__sep" aria-hidden>
            /
          </span>
          {p.to ? <Link to={p.to}>{p.label}</Link> : <span className="crumbs__current">{p.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function AppShell() {
  const { user, status, login, logout } = useAuth();
  const [theme, setTheme] = useState<Theme>(() => getStoredTheme());
  const { pathname } = useLocation();

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const initials = (user?.display_name ?? 'Гость')
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  return (
    <div className="shell">
      {/* ─── узкий рейл с логотипом ─── */}
      <aside className="rail no-print">
        <Link to="/" className="rail__logo" title="SourceCraft Repo Health">
          ❤
        </Link>
        <NavLink to="/" end className={({ isActive }) => `rail__btn ${isActive ? 'active' : ''}`} title="Рейтинг">
          ▤
        </NavLink>
        <NavLink to="/compare" className={({ isActive }) => `rail__btn ${isActive ? 'active' : ''}`} title="Сравнение">
          ⇆
        </NavLink>
        <NavLink
          to="/dashboard"
          className={() => `rail__btn ${pathname.startsWith('/dashboard') ? 'active' : ''}`}
          title="Мои репозитории"
        >
          ◧
        </NavLink>
        <span className="spacer" />
        <button
          type="button"
          className="rail__btn"
          onClick={() => setTheme((t) => (t === 'dark' ? 'light' : t === 'light' ? 'system' : 'dark'))}
          title={`Тема: ${theme === 'system' ? 'как в системе' : theme === 'dark' ? 'тёмная' : 'светлая'}`}
          aria-label="Переключить тему"
        >
          {theme === 'system' ? '◐' : theme === 'dark' ? '☾' : '☀'}
        </button>
      </aside>

      {/* ─── боковая навигация ─── */}
      <aside className="sidebar no-print">
        <div className="sidebar__user">
          <span className="sidebar__avatar">{status === 'authenticated' ? initials : '?'}</span>
          <span className="stack-sm" style={{ gap: 0, minWidth: 0 }}>
            <span className="sidebar__name">
              {status === 'authenticated' ? user?.display_name : 'Repo Health'}
            </span>
            <span className="sidebar__login">
              {status === 'authenticated' ? user?.login : 'SourceCraft'}
            </span>
          </span>
        </div>

        <div className="nav-group">
          <span className="nav-group__title">Обзор</span>
          <NavLink to="/" end className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span className="nav-item__icon" aria-hidden>
              ▤
            </span>
            Рейтинг
          </NavLink>
          <NavLink to="/compare" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span className="nav-item__icon" aria-hidden>
              ⇆
            </span>
            Сравнение
          </NavLink>
          <NavLink to="/methodology" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
            <span className="nav-item__icon" aria-hidden>
              ƒ
            </span>
            Методика
          </NavLink>
        </div>

        <div className="nav-group">
          <span className="nav-group__title">Мои проекты</span>
          {status === 'authenticated' ? (
            <>
              <NavLink
                to="/dashboard"
                end
                className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              >
                <span className="nav-item__icon" aria-hidden>
                  ◧
                </span>
                Мои репозитории
              </NavLink>
              <button type="button" className="nav-item" onClick={() => void logout()}>
                <span className="nav-item__icon" aria-hidden>
                  ⎋
                </span>
                Выйти
              </button>
            </>
          ) : (
            <button type="button" className="nav-item" onClick={() => login('/dashboard')}>
              <span className="nav-item__icon" aria-hidden>
                →
              </span>
              Войти через Я ID
            </button>
          )}
        </div>

        <div className="sidebar__footer">
          {IS_MOCK ? (
            <span className="badge badge--warn" title="Данные из снимка, а не из боевого API">
              демо-данные
            </span>
          ) : (
            <span className="badge badge--good" title="Рейтинг и отчёты приходят из API сервиса">
              боевые данные
            </span>
          )}
          {!IS_MOCK && IS_AUTH_MOCK ? (
            <span className="badge badge--warn" style={{ marginLeft: 6 }} title="Я ID ещё не подключён">
              кабинет: демо
            </span>
          ) : null}
          <p className="text-subtle" style={{ marginTop: 8 }}>
            Оценка здоровья открытых репозиториев SourceCraft
          </p>
        </div>
      </aside>

      {/* ─── контент ─── */}
      <div className="main">
        <header className="topbar no-print">
          <Breadcrumbs />
          <span className="spacer" />
          {status === 'authenticated' && user ? (
            <Dropdown
              trigger={({ toggle, open }) => (
                <button type="button" className="btn btn--sm" onClick={toggle} aria-expanded={open}>
                  {user.display_name} ▾
                </button>
              )}
            >
              {(close) => (
                <>
                  <Link to="/dashboard" className="dropdown__item" onClick={close}>
                    Мои репозитории
                    <span>{user.email ?? user.login}</span>
                  </Link>
                  <button
                    type="button"
                    className="dropdown__item"
                    onClick={() => {
                      void logout();
                      close();
                    }}
                  >
                    Выйти
                    <span>Завершить сессию Я ID</span>
                  </button>
                </>
              )}
            </Dropdown>
          ) : (
            <button type="button" className="btn btn--primary btn--sm" onClick={() => login('/dashboard')}>
              Войти через Я ID
            </button>
          )}
        </header>

        <main className="content">
          {IS_MOCK ? (
            <div className="banner banner--warn no-print" style={{ marginBottom: 'var(--space-5)' }}>
              <span aria-hidden>⚠</span>
              <div>
                <strong>Демо-режим.</strong> Интерфейс работает на снимке данных SourceCraft от 20–21
                сентября 2026&nbsp;года (27&nbsp;761 репозиторий), Score посчитан временной формулой из
                <span className="mono"> tools/build_mock_data.py</span>. Боевые значения приходят из витрины
                сервиса — переключается флагом <span className="mono">VITE_DATA_SOURCE=api</span>.
              </div>
            </div>
          ) : null}
          {!IS_MOCK && IS_AUTH_MOCK ? (
            <div className="banner no-print" style={{ marginBottom: 'var(--space-5)' }}>
              <span aria-hidden>ⓘ</span>
              <div>
                Рейтинг и страницы анализа работают на боевом API сервиса. Вход через Я&nbsp;ID и
                анализ собственного репозитория пока идут на демо-данных — они включатся, когда
                бэкенд поднимет <span className="mono">/auth/yandex/login</span> и{' '}
                <span className="mono">/analyses</span>.
              </div>
            </div>
          ) : null}
          <Outlet />
        </main>

        <footer className="footer no-print">
          <div className="row-wrap" style={{ justifyContent: 'space-between' }}>
            <span>SourceCraft Repo Health — оценка здоровья открытых репозиториев.</span>
            <span className="row-wrap" style={{ gap: 16 }}>
              <Link to="/methodology">Методика расчёта</Link>
              <a href="https://sourcecraft.dev/find/repositories" target="_blank" rel="noreferrer">
                Каталог репозиториев
              </a>
            </span>
          </div>
        </footer>
      </div>
    </div>
  );
}
