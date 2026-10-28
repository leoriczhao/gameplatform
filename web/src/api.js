async function fail(resp) {
  let message = `HTTP ${resp.status}`;
  let code;
  let detail;
  try {
    const data = await resp.json();
    detail = data?.detail;
    if (typeof detail === "string") {
      message = detail;
    } else if (detail && typeof detail === "object") {
      // v2 API（docs/design/17 §5.1）的错误是 {code, message}，UI 需要 code 分支
      message = detail.message || message;
      code = detail.code;
    } else if (data?.code) {
      message = data.message || message;
      code = data.code;
    }
  } catch (e) {
    /* keep */
  }
  const err = new Error(message);
  err.status = resp.status;
  if (code) err.code = code;
  if (detail !== undefined) err.detail = detail;
  throw err;
}

export async function post(path, body, token, signal) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, {
    method: "POST",
    signal,
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await fail(resp);
  return resp.json();
}

export async function putJson(path, body, token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, {
    method: "PUT",
    headers,
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw await fail(resp);
  return resp.json();
}

export async function getJson(path, token, signal) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { headers, signal });
  if (!resp.ok) throw await fail(resp);
  return resp.json();
}

export async function uploadFile(path, formData, token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { method: "POST", headers, body: formData });
  if (!resp.ok) throw await fail(resp);
  return resp.json();
}

export async function del(path, token) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(path, { method: "DELETE", headers });
  if (!resp.ok) throw await fail(resp);
  return resp.json();
}
