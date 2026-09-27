import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '@/auth/AuthProvider';
import { Card, Spinner } from '@/components/ui';

/** Возврат от Я ID: забираем токен из query, кладём в хранилище и идём дальше. */
export function AuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { completeLogin } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    handled.current = true;

    // Яндекс в implicit-потоке возвращает токен во фрагменте адреса, а сервис
    // при code-потоке и демо-входе — обычным параметром запроса.
    const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
    const token = params.get('token') ?? hash.get('access_token');
    const next = params.get('next') ?? hash.get('state') ?? '/dashboard';
    const err = params.get('error_description') ?? params.get('error')
      ?? hash.get('error_description') ?? hash.get('error');

    if (err) {
      setError(err);
      return;
    }
    if (!token) {
      setError('Я ID не передал токен доступа. Попробуйте войти ещё раз.');
      return;
    }

    void completeLogin(token)
      .then(() => navigate(next, { replace: true }))
      .catch(() => setError('Не удалось получить профиль пользователя.'));
  }, [params, completeLogin, navigate]);

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '50vh' }}>
      <Card style={{ maxWidth: 460 }}>
        {error ? (
          <div className="stack-sm">
            <h2>Вход не завершён</h2>
            <p className="text-muted">{error}</p>
            <button type="button" className="btn btn--primary" onClick={() => navigate('/login', { replace: true })}>
              Попробовать снова
            </button>
          </div>
        ) : (
          <div className="stack-sm">
            <h2>Завершаем вход…</h2>
            <Spinner label="Проверяем токен Я ID" />
          </div>
        )}
      </Card>
    </div>
  );
}
