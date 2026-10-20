async function fail(resp) {
  let detail = `HTTP ${resp.status}`;
  try {
    const data = await resp.json();
    detail = data.detail || detail;
  } catch (e) {
    /* keep */
  }
  const err = new Error(detail);
  err.status = resp.status;
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
