const state = {
  token: window.localStorage.getItem("nab_token") || "",
  refreshToken: window.localStorage.getItem("nab_refresh_token") || "",
  trendChart: null,
  compareChart: null,
  complexSearchDebounceTimer: null,
  complexSearchRequestId: 0,
};

const qs = (selector) => document.querySelector(selector);

function setStatus(target, message) {
  qs(target).textContent = message;
}

function authHeader() {
  if (!state.token) return {};
  return { Authorization: `Bearer ${state.token}` };
}

async function api(path, options = {}) {
  const isAuthEndpoint =
    path.startsWith("/auth/login") ||
    path.startsWith("/auth/register") ||
    path.startsWith("/auth/refresh") ||
    path.startsWith("/auth/logout");

  const request = async (useAuth = true) =>
    fetch(path, {
      headers: {
        "Content-Type": "application/json",
        ...(useAuth ? authHeader() : {}),
        ...(options.headers || {}),
      },
      ...options,
    });

  let response = await request(true);
  if (response.status === 401 && !isAuthEndpoint && state.refreshToken) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      response = await request(true);
    }
  }

  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch (_e) {
    data = { detail: text };
  }

  if (!response.ok) {
    const detail = data.detail || `HTTP ${response.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}

function renderUserBadge(text) {
  qs("#userBadge").textContent = text;
}

function renderBillingBadge(planCode, status) {
  const normalizedPlan = planCode || "UNKNOWN";
  const normalizedStatus = status || "UNKNOWN";
  qs("#billingPlanBadge").textContent = `플랜: ${normalizedPlan} (${normalizedStatus})`;
}

function extractComplexNoFromInput(raw) {
  const value = (raw || "").trim();
  if (!value) return null;

  // Case 1: plain numeric input (e.g. "2977")
  if (/^\d+$/.test(value)) {
    return Number(value);
  }

  // Case 2: full Naver URL that includes /complexes/{complexNo}
  const pathMatch = value.match(/\/complexes\/(\d+)/);
  if (pathMatch) {
    return Number(pathMatch[1]);
  }

  // Case 3: query string style (complexNo / selectedComplexNo)
  try {
    const parsed = new URL(value);
    const q1 = parsed.searchParams.get("complexNo");
    if (q1 && /^\d+$/.test(q1)) return Number(q1);
    const q2 = parsed.searchParams.get("selectedComplexNo");
    if (q2 && /^\d+$/.test(q2)) return Number(q2);
  } catch (_e) {
    // Ignore URL parse errors; fallback regex below.
  }

  const queryMatch = value.match(/(?:complexNo|selectedComplexNo)=([0-9]+)/);
  if (queryMatch) {
    return Number(queryMatch[1]);
  }
  return null;
}

async function parseComplexUrl() {
  const raw = qs("#watchComplexUrl").value;
  const complexNo = extractComplexNoFromInput(raw);
  if (!complexNo) {
    throw new Error("유효한 네이버 단지 URL 또는 complexNo를 입력해주세요.");
  }
  qs("#watchComplexNo").value = String(complexNo);
  setStatus("#authStatus", `complexNo 추출 완료: ${complexNo}`);
}

function renderComplexSearchResults(items, hasKeyword = false) {
  const root = qs("#watchComplexSearchList");
  root.innerHTML = "";

  if (!items.length) {
    if (hasKeyword) {
      root.innerHTML = '<div class="muted">검색 결과가 없습니다.</div>';
    }
    return;
  }

  items.forEach((item) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "alt";
    btn.style.width = "100%";
    btn.style.textAlign = "left";
    btn.style.marginBottom = "6px";

    const address = [item.sido_name, item.gugun_name, item.dong_name].filter(Boolean).join(" ");
    const typeName = item.real_estate_type_name ? ` (${item.real_estate_type_name})` : "";
    btn.textContent = `${item.complex_name}${typeName} | ${item.complex_no}${address ? ` | ${address}` : ""}`;

    btn.addEventListener("click", () => {
      qs("#watchComplexNo").value = String(item.complex_no);
      qs("#watchComplexName").value = item.complex_name || "";
      setStatus("#authStatus", `단지 선택 완료: ${item.complex_name} (${item.complex_no})`);
    });

    root.appendChild(btn);
  });
}

async function performComplexSearch({ isAuto = false } = {}) {
  const keyword = qs("#watchComplexKeyword").value.trim();
  if (keyword.length < 2) {
    renderComplexSearchResults([], false);
    if (!isAuto) {
      throw new Error("단지명은 2자 이상 입력해주세요.");
    }
    return;
  }

  const requestId = ++state.complexSearchRequestId;
  const query = new URLSearchParams({
    keyword,
    limit: "8",
  });
  const data = await api(`/crawler/search/complexes?${query.toString()}`);
  if (requestId !== state.complexSearchRequestId) {
    return;
  }

  renderComplexSearchResults(data.items || [], true);
  setStatus("#authStatus", `단지 검색 완료: ${data.count}건`);
}

async function searchComplexes() {
  await performComplexSearch({ isAuto: false });
}

function onWatchComplexKeywordInput() {
  if (state.complexSearchDebounceTimer) {
    clearTimeout(state.complexSearchDebounceTimer);
  }
  state.complexSearchDebounceTimer = window.setTimeout(() => {
    performComplexSearch({ isAuto: true }).catch((err) => {
      const message = err instanceof Error ? err.message : String(err);
      setStatus("#authStatus", message);
    });
  }, 350);
}

async function register() {
  const email = qs("#email").value.trim();
  const password = qs("#password").value;
  const data = await api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setStatus("#authStatus", `회원가입 완료: ${data.email}`);
}

async function login() {
  const email = qs("#email").value.trim();
  const password = qs("#password").value;
  const data = await api("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  state.token = data.access_token;
  state.refreshToken = data.refresh_token;
  window.localStorage.setItem("nab_token", state.token);
  window.localStorage.setItem("nab_refresh_token", state.refreshToken);
  renderUserBadge(`로그인됨: ${email}`);
  setStatus("#authStatus", "로그인 성공");
  await loadBillingMe();
}

async function refreshAccessToken() {
  if (!state.refreshToken) return false;
  const response = await fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: state.refreshToken }),
  });
  if (!response.ok) {
    state.token = "";
    state.refreshToken = "";
    window.localStorage.removeItem("nab_token");
    window.localStorage.removeItem("nab_refresh_token");
    renderUserBadge("로그인 필요");
    return false;
  }
  const data = await response.json();
  state.token = data.access_token;
  state.refreshToken = data.refresh_token;
  window.localStorage.setItem("nab_token", state.token);
  window.localStorage.setItem("nab_refresh_token", state.refreshToken);
  return true;
}

async function logout() {
  if (state.refreshToken) {
    await api("/auth/logout", {
      method: "POST",
      body: JSON.stringify({ refresh_token: state.refreshToken }),
    }).catch(() => {});
  }
  state.token = "";
  state.refreshToken = "";
  window.localStorage.removeItem("nab_token");
  window.localStorage.removeItem("nab_refresh_token");
  renderUserBadge("로그인 필요");
  renderBillingBadge("FREE", "LOGGED_OUT");
  setStatus("#authStatus", "로그아웃 완료");
}

async function me() {
  const data = await api("/me");
  renderUserBadge(`사용자: ${data.email}`);
  setStatus("#authStatus", `내 계정: ${data.email}`);
  await loadBillingMe();
  await loadNotificationSettings();
}

async function loadBillingMe() {
  const data = await api("/billing/me");
  renderBillingBadge(data.plan_code, data.status);
  const limits = data.limits || {};
  const watchLimit = limits.watch_complex_limit ?? "무제한";
  const presetLimit = limits.preset_limit ?? "무제한";
  const compareLimit = limits.compare_complex_limit ?? "무제한";
  const manualDispatch = limits.manual_alert_dispatch ? "가능" : "불가";
  setStatus(
    "#billingStatus",
    `플랜=${data.plan_code}, 관심단지=${watchLimit}, 프리셋=${presetLimit}, 비교단지=${compareLimit}, 수동알림=${manualDispatch}`
  );
}

async function startDummyCheckout() {
  const data = await api("/billing/checkout-sessions", {
    method: "POST",
    body: JSON.stringify({ plan_code: "PRO" }),
  });
  qs("#billingCheckoutToken").value = data.checkout_token || "";
  setStatus(
    "#billingStatus",
    `결제 세션 생성 완료: plan=${data.plan_code}, amount=${data.amount_krw} KRW, token=${data.checkout_token}`
  );
}

async function completeDummyCheckout() {
  const checkoutToken = qs("#billingCheckoutToken").value.trim();
  if (!checkoutToken) {
    throw new Error("checkout_token이 필요합니다. 먼저 결제 시작 버튼을 눌러주세요.");
  }
  const data = await api(`/billing/checkout-sessions/${checkoutToken}/complete`, {
    method: "POST",
  });
  renderBillingBadge(data.activated_plan_code, data.entitlements?.status || "ACTIVE");
  setStatus("#billingStatus", `결제 완료 처리됨: 활성 플랜=${data.activated_plan_code}`);
}

async function addWatchComplex() {
  const complexNo = Number(qs("#watchComplexNo").value);
  const complexName = qs("#watchComplexName").value.trim();
  const data = await api("/me/watch-complexes", {
    method: "POST",
    body: JSON.stringify({
      complex_no: complexNo,
      complex_name: complexName || null,
    }),
  });
  setStatus("#authStatus", `관심 단지 등록 완료: ${data.complex_no}`);
  await loadWatchComplexes();
}

async function loadWatchComplexes() {
  const data = await api("/me/watch-complexes");
  const root = qs("#watchList");
  root.innerHTML = "";
  if (!data.items.length) {
    root.innerHTML = '<div class="muted">등록된 단지가 없습니다.</div>';
    return;
  }
  data.items.forEach((item) => {
    const tag = document.createElement("div");
    tag.className = "pill";
    tag.textContent = `${item.complex_no} ${item.complex_name || ""}`.trim();
    root.appendChild(tag);
  });
}

function renderLiveWatchListings(items) {
  const root = qs("#liveWatchList");
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = '<div class="muted">실시간 조회 대상 단지가 없습니다.</div>';
    return;
  }

  items.forEach((group) => {
    const block = document.createElement("div");
    block.style.marginBottom = "10px";

    const title = document.createElement("div");
    title.className = "pill";
    title.textContent = `${group.complex_no} ${group.complex_name || ""} (매물 ${group.article_count || 0}건)`.trim();
    block.appendChild(title);

    if (group.error) {
      const errorLine = document.createElement("div");
      errorLine.className = "muted";
      errorLine.textContent = `조회 실패: ${group.error}`;
      block.appendChild(errorLine);
      root.appendChild(block);
      return;
    }

    const articles = Array.isArray(group.articles) ? group.articles : [];
    if (!articles.length) {
      const emptyLine = document.createElement("div");
      emptyLine.className = "muted";
      emptyLine.textContent = "표시할 매물이 없습니다.";
      block.appendChild(emptyLine);
      root.appendChild(block);
      return;
    }

    articles.forEach((article) => {
      const line = document.createElement("div");
      line.className = "muted";
      line.textContent =
        `${article.article_name || "-"} | ${article.trade_type || "-"} | ` +
        `${article.price || "-"} | ${article.floor_info || "-"}`;
      block.appendChild(line);
    });
    root.appendChild(block);
  });
}

async function loadLiveWatchComplexes() {
  const page = Number(qs("#liveWatchPage").value || "1");
  const maxPerComplex = Number(qs("#liveWatchMax").value || "10");
  const data = await api(`/me/watch-complexes/live?page=${page}&max_per_complex=${maxPerComplex}`);
  renderLiveWatchListings(data.items || []);
  setStatus("#authStatus", `실시간 매물 조회 완료: ${data.count}개 단지`);
}

async function ingestNow() {
  const complexNo = Number(qs("#ingestComplexNo").value);
  const page = Number(qs("#ingestPage").value || "1");
  const data = await api(`/crawler/ingest/${complexNo}?page=${page}`, {
    method: "POST",
  });

  const pagesFetched = Number(data.pages_fetched || 0);
  const listingCount = Number(data.listing_count || 0);
  const baseLine = `데이터 새로고침 완료: 단지 ${complexNo}에서 ${listingCount}건을 수집했습니다.`;
  const pageLine = pagesFetched > 0 ? ` 확인한 페이지 수: ${pagesFetched}페이지.` : "";

  let trendLine = "";
  try {
    const trend = await api(`/analytics/trend/${complexNo}?days=7`);
    const series = Array.isArray(trend.series) ? trend.series : [];
    const latest = series.at(-1);
    if (latest && typeof latest === "object") {
      const avg = Math.round(Number(latest.avg_price_manwon || 0));
      const min = Number(latest.min_price_manwon || 0);
      const max = Number(latest.max_price_manwon || 0);
      const count = Number(latest.listing_count || 0);
      trendLine = ` 최근 집계 기준 평균 ${avg}만원 / 최저 ${min}만원 / 최고 ${max}만원 (집계 매물 ${count}건).`;
    } else {
      trendLine = " 아직 분석 데이터가 충분하지 않아 시세 요약은 표시되지 않았습니다.";
    }
  } catch (_err) {
    trendLine = " 수집은 완료됐지만 시세 요약 조회는 실패했습니다.";
  }

  setStatus("#ingestStatus", `${baseLine}${pageLine}${trendLine}`);
}

async function loadMeta() {
  const data = await api("/meta");
  setStatus(
    "#ingestStatus",
    `운영 정보: interval=${data.crawler_interval_minutes}분, retry=${data.crawler_max_retry}회. 일반 사용보다는 운영 점검용 정보입니다.`
  );
}

async function loadNotificationSettings() {
  const data = await api("/me/notification-settings");
  qs("#notifyEmailEnabled").checked = Boolean(data.email_enabled);
  qs("#notifyEmailAddress").value = data.email_address || "";
  qs("#notifyTelegramEnabled").checked = Boolean(data.telegram_enabled);
  qs("#notifyTelegramChatId").value = data.telegram_chat_id || "";
  qs("#notifyBargainEnabled").checked = Boolean(data.bargain_alert_enabled);
  qs("#notifyLookbackDays").value = String(data.bargain_lookback_days || 30);
  qs("#notifyDiscountThreshold").value = String(data.bargain_discount_threshold || 0.08);
  setStatus("#notifyStatus", "알림 설정 조회 완료");
}

async function saveNotificationSettings() {
  const payload = {
    email_enabled: qs("#notifyEmailEnabled").checked,
    email_address: qs("#notifyEmailAddress").value.trim() || null,
    telegram_enabled: qs("#notifyTelegramEnabled").checked,
    telegram_chat_id: qs("#notifyTelegramChatId").value.trim() || null,
    bargain_alert_enabled: qs("#notifyBargainEnabled").checked,
    bargain_lookback_days: Number(qs("#notifyLookbackDays").value || "30"),
    bargain_discount_threshold: Number(qs("#notifyDiscountThreshold").value || "0.08"),
  };
  await api("/me/notification-settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  setStatus("#notifyStatus", "알림 설정 저장 완료");
}

async function dispatchAlertNow() {
  const data = await api("/me/alerts/bargains/dispatch", { method: "POST" });
  setStatus(
    "#notifyStatus",
    `발송 완료: email=${data.email_sent}, telegram=${data.telegram_sent}, 후보=${data.candidate_count}`
  );
}

function upsertChart(targetId, chartStateKey, config) {
  const canvas = qs(targetId);
  if (state[chartStateKey]) {
    state[chartStateKey].destroy();
  }
  state[chartStateKey] = new Chart(canvas, config);
}

function renderBargainRows(items) {
  const body = qs("#bargainBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">조건에 맞는 급매 후보가 없습니다.</td></tr>';
    return;
  }

  items.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${item.complex_name || item.complex_no || "-"}</td>
      <td>${item.article_no}</td>
      <td>${item.article_name || "-"}</td>
      <td>${item.trade_type_name || "-"}</td>
      <td>${item.deal_price_text || "-"}</td>
      <td>${Math.round(item.baseline_median_manwon)}</td>
      <td>${(item.discount_rate * 100).toFixed(2)}%</td>
    `;
    body.appendChild(tr);
  });
}

async function loadTrend() {
  const complexNo = Number(qs("#trendComplexNo").value);
  const days = Number(qs("#trendDays").value || "30");
  const data = await api(`/analytics/trend/${complexNo}?days=${days}`);
  const labels = data.series.map((row) => row.date);
  const values = data.series.map((row) => row.avg_price_manwon);

  upsertChart("#trendChart", "trendChart", {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: `단지 ${complexNo} 평균가(만원)`,
          data: values,
          borderColor: "#0369a1",
          backgroundColor: "rgba(3, 105, 161, 0.18)",
          fill: true,
          tension: 0.2,
        },
      ],
    },
    options: { responsive: true, maintainAspectRatio: false },
  });
}

async function loadCompare() {
  const raw = qs("#compareComplexNos").value;
  const days = Number(qs("#compareDays").value || "30");
  const complexNos = raw
    .split(",")
    .map((v) => Number(v.trim()))
    .filter((v) => Number.isFinite(v) && v > 0);
  if (complexNos.length < 2) throw new Error("비교 단지는 최소 2개가 필요합니다.");

  const query = new URLSearchParams();
  query.set("days", String(days));
  complexNos.forEach((no) => query.append("complex_nos", String(no)));

  const data = await api(`/analytics/compare?${query.toString()}`);
  const palette = ["#0ea5e9", "#ef4444", "#16a34a", "#f59e0b", "#475569", "#0891b2"];

  const labelsSet = new Set();
  complexNos.forEach((no) => {
    (data.series[String(no)] || data.series[no] || []).forEach((row) => labelsSet.add(row.date));
  });
  const labels = Array.from(labelsSet).sort();

  const datasets = complexNos.map((no, idx) => {
    const rows = data.series[String(no)] || data.series[no] || [];
    const map = new Map(rows.map((r) => [r.date, r.avg_price_manwon]));
    return {
      label: `단지 ${no}`,
      data: labels.map((label) => map.get(label) ?? null),
      borderColor: palette[idx % palette.length],
      spanGaps: true,
      tension: 0.2,
    };
  });

  upsertChart("#compareChart", "compareChart", {
    type: "line",
    data: { labels, datasets },
    options: { responsive: true, maintainAspectRatio: false },
  });
}

async function loadBargains() {
  const complexNo = Number(qs("#bargainComplexNo").value);
  const lookbackDays = Number(qs("#bargainDays").value || "30");
  const threshold = Number(qs("#bargainThreshold").value || "0.08");
  const data = await api(
    `/analytics/bargains/${complexNo}?lookback_days=${lookbackDays}&discount_threshold=${threshold}`
  );
  renderBargainRows(data.items || []);
}

async function loadMyBargainAlerts() {
  const lookbackDays = Number(qs("#bargainDays").value || "30");
  const threshold = Number(qs("#bargainThreshold").value || "0.08");
  const data = await api(
    `/me/alerts/bargains?lookback_days=${lookbackDays}&discount_threshold=${threshold}`
  );
  renderBargainRows(data.items || []);
}

function bind(id, fn) {
  qs(id).addEventListener("click", async () => {
    try {
      await fn();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setStatus("#authStatus", message);
      setStatus("#ingestStatus", message);
    }
  });
}

bind("#registerBtn", register);
bind("#loginBtn", login);
bind("#meBtn", me);
bind("#logoutBtn", logout);
bind("#searchComplexBtn", searchComplexes);
bind("#parseComplexUrlBtn", parseComplexUrl);
bind("#addWatchBtn", addWatchComplex);
bind("#loadWatchBtn", loadWatchComplexes);
bind("#loadLiveWatchBtn", loadLiveWatchComplexes);
bind("#ingestBtn", ingestNow);
bind("#metaBtn", loadMeta);
bind("#billingMeBtn", loadBillingMe);
bind("#billingCheckoutBtn", startDummyCheckout);
bind("#billingCompleteBtn", completeDummyCheckout);
bind("#loadNotifyBtn", loadNotificationSettings);
bind("#saveNotifyBtn", saveNotificationSettings);
bind("#dispatchAlertBtn", dispatchAlertNow);
bind("#loadTrendBtn", loadTrend);
bind("#loadCompareBtn", loadCompare);
bind("#loadBargainBtn", loadBargains);
bind("#loadMyBargainBtn", loadMyBargainAlerts);
qs("#watchComplexKeyword").addEventListener("input", onWatchComplexKeywordInput);

if (state.token) {
  me().catch(() => {
    renderUserBadge("로그인 필요");
    renderBillingBadge("FREE", "LOGGED_OUT");
  });
}
