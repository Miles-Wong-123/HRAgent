export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { token, method = 'GET', body, signal } = {}) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const multipart = body instanceof FormData;
  if (body !== undefined && !multipart) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method, headers, body: multipart ? body : JSON.stringify(body),
      signal: signal ?? AbortSignal.timeout(20000),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError(0, '无法连接后端，请确认 8000 端口的服务已启动。');
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map(item => `${item.loc?.slice(1).join('.') || '参数'}：${item.msg}`).join('；')
      : typeof detail === 'string' ? detail : response.status >= 500
        ? '服务暂时不可用。请稍后重试或查看后端日志。' : '请求未成功，请稍后重试。';
    throw new ApiError(response.status, message);
  }
  return data;
}
