const state = {
  token: window.localStorage.getItem("nab_token") || "",
  refreshToken: window.localStorage.getItem("nab_refresh_token") || "",
  trendChart: null,
  compareChart: null,
  complexSearchDebounceTimer: null,
  complexSearchRequestId: 0,
  liveWatchRows: [],
  analyticsTradeType: "ALL",
  analyticsConversionRate: 5.1,
};

const qs = (selector) => document.querySelector(selector);

function setStatus(target, message) {
  const node = qs(target);
  if (!node) return;
  node.textContent = message;
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

function setAuthControls(loggedIn, email = "") {
  const guest = qs("#authGuestControls");
  const user = qs("#authUserControls");
  if (!guest || !user) return;

  guest.classList.toggle("active", !loggedIn);
  user.classList.toggle("active", loggedIn);
  if (loggedIn) {
    qs("#authEmailDisplay").textContent = email ? `로그인 사용자: ${email}` : "로그인 사용자";
  }
}

function renderBillingBadge(planCode, status) {
  const normalizedPlan = planCode || "UNKNOWN";
  const normalizedStatus = status || "UNKNOWN";
  qs("#billingPlanBadge").textContent = `플랜: ${normalizedPlan} (${normalizedStatus})`;
}

function extractComplexNoFromInput(raw) {
  const value = (raw || "").trim();
  if (!value) return null;

  if (/^\d+$/.test(value)) {
    return Number(value);
  }

  const pathMatch = value.match(/\/complexes\/(\d+)/);
  if (pathMatch) {
    return Number(pathMatch[1]);
  }

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
    throw new Error("유효한 네이버 단지 URL 또는 단지 번호를 입력해주세요.");
  }
  qs("#watchComplexNo").value = String(complexNo);
  setStatus("#watchStatus", `단지 번호 추출 완료: ${complexNo}`);
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
      setStatus("#watchStatus", `단지 선택 완료: ${item.complex_name} (${item.complex_no})`);
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
  setStatus("#watchStatus", `단지 검색 완료: ${data.count}건`);
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
      setStatus("#watchStatus", message);
    });
  }, 350);
}

async function register() {
  const email = qs("#email").value.trim();
  const password = qs("#password").value;
  const inviteCode = qs("#inviteCode")?.value?.trim() || null;
  const data = await api("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, invite_code: inviteCode }),
  });
  if (data.email_verification_required) {
    const sentMessage = data.email_verification_sent
      ? "인증 메일을 발송했습니다."
      : `인증 메일 발송 실패(${data.email_verification_message || "원인 미상"})`;
    const expiresAt = data.email_verification_expires_at
      ? ` 만료 시각: ${formatTimestamp(data.email_verification_expires_at)}`
      : "";
    const devLink = data.dev_email_verification_link
      ? ` 개발 모드 인증 링크: ${data.dev_email_verification_link}`
      : "";
    setStatus(
      "#authStatus",
      `회원가입 완료: ${data.email}. 이메일 인증 후 로그인할 수 있습니다. ${sentMessage}${expiresAt}${devLink}`
    );
    return;
  }
  setStatus("#authStatus", `회원가입 완료: ${data.email}. 바로 로그인할 수 있습니다.`);
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
  setAuthControls(true, email);
  renderUserBadge(`로그인됨: ${email}`);
  setStatus("#authStatus", "로그인 성공");
  await loadBillingMe();
  await hydrateWatchDashboard();
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
    setAuthControls(false);
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
  setAuthControls(false);
  renderUserBadge("로그인 필요");
  renderBillingBadge("FREE", "LOGGED_OUT");
  setStatus("#authStatus", "로그아웃 완료");
}

async function me() {
  const data = await api("/me");
  setAuthControls(true, data.email);
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
  setStatus("#watchStatus", `관심 단지 등록 완료: ${data.complex_no}`);
  await loadWatchComplexes();
}

function formatTimestamp(iso) {
  if (!iso) return "-";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString("ko-KR", { hour12: false });
}

async function deleteWatchComplex(watchId) {
  await api(`/me/watch-complexes/${watchId}`, { method: "DELETE" });
  setStatus("#watchStatus", `관심 단지 삭제 완료: ID ${watchId}`);
  await loadWatchComplexes();
}

function renderWatchComplexRows(items) {
  const body = qs("#watchBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="5" class="muted">등록된 단지가 없습니다.</td></tr>';
    return;
  }

  items.forEach((item) => {
    const tr = document.createElement("tr");
    const location = [item.sido_name, item.gugun_name, item.dong_name].filter(Boolean).join(" ");
    tr.innerHTML = `
      <td class="mono">${item.complex_no}</td>
      <td>${item.complex_name || "-"}</td>
      <td>${location || "-"}</td>
      <td>${formatTimestamp(item.created_at)}</td>
      <td><button type="button" class="warn" data-watch-id="${item.id}">삭제</button></td>
    `;
    body.appendChild(tr);
  });

  body.querySelectorAll("button[data-watch-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const watchId = Number(button.getAttribute("data-watch-id"));
      if (!watchId) return;
      try {
        await deleteWatchComplex(watchId);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setStatus("#watchStatus", message);
      }
    });
  });
}

async function loadWatchComplexes() {
  const data = await api("/me/watch-complexes");
  const items = Array.isArray(data.items) ? data.items : [];
  renderWatchComplexRows(items);
  setStatus("#watchStatus", `관심 단지 ${items.length}건`);
}

function renderCollectionStatus(data) {
  const auto = data.auto_collect || {};
  const times = Array.isArray(auto.times) ? auto.times : [];
  const timesText = times.length ? times.join(", ") : "미설정";
  const hint = [
    `자동수집: ${auto.enabled ? "사용 중" : "비활성"}`,
    `시간대: ${auto.timezone || "-"}`,
    `실행 시각: ${timesText}`,
    `폴링주기: ${auto.poll_seconds || "-"}초`,
    `재사용 버킷: ${auto.reuse_bucket_hours ?? "-"}시간`,
    "현재 자동수집 주기/재사용 버킷은 서버 전역 설정입니다.",
  ].join(" | ");
  qs("#collectionAutoCollectHint").textContent = hint;

  const body = qs("#collectionStatusBody");
  body.innerHTML = "";
  const items = Array.isArray(data.items) ? data.items : [];
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="6" class="muted">등록된 관심 단지가 없습니다.</td></tr>';
    setStatus("#collectionStatusNote", "조회 결과가 없습니다.");
    return;
  }

  items.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="mono">${item.complex_no}</td>
      <td>${item.complex_name || "-"}</td>
      <td>${formatTimestamp(item.latest_collected_at)}</td>
      <td>${item.latest_listing_count ?? "-"}</td>
      <td>${item.last_run_status || "-"}</td>
      <td>${item.auto_collect_target ? "예" : "아니오"}</td>
    `;
    body.appendChild(tr);
  });

  setStatus("#collectionStatusNote", `${items.length}개 단지의 수집 이력을 확인했습니다.`);
}

async function loadCollectionStatus() {
  const data = await api("/me/watch-complexes/collection-status");
  renderCollectionStatus(data);
}

async function loadSchedulerConfig() {
  const data = await api("/scheduler/config");
  qs("#schedulerEnabled").checked = Boolean(data.enabled);
  qs("#schedulerTimezone").value = data.timezone || "Asia/Seoul";
  qs("#schedulerTimesCsv").value = data.times_csv || "";
  qs("#schedulerPollSeconds").value = String(data.poll_seconds ?? 20);
  qs("#schedulerReuseBucketHours").value = String(data.reuse_bucket_hours ?? 12);
  setStatus(
    "#collectionStatusNote",
    `스케줄 설정 로드 완료: ${data.enabled ? "활성" : "비활성"} / ${data.times_csv || "-"} / 재사용 ${
      data.reuse_bucket_hours
    }시간`
  );
}

async function saveSchedulerConfig() {
  const enabled = qs("#schedulerEnabled").checked;
  const timezone = qs("#schedulerTimezone").value.trim();
  const timesCsv = qs("#schedulerTimesCsv").value.trim();
  const pollSeconds = Number(qs("#schedulerPollSeconds").value || "20");
  const reuseBucketHours = Number(qs("#schedulerReuseBucketHours").value || "12");

  const data = await api("/scheduler/config", {
    method: "PUT",
    body: JSON.stringify({
      enabled,
      timezone,
      times_csv: timesCsv,
      poll_seconds: pollSeconds,
      reuse_bucket_hours: reuseBucketHours,
    }),
  });
  qs("#schedulerEnabled").checked = Boolean(data.enabled);
  qs("#schedulerTimezone").value = data.timezone || "Asia/Seoul";
  qs("#schedulerTimesCsv").value = data.times_csv || "";
  qs("#schedulerPollSeconds").value = String(data.poll_seconds ?? 20);
  qs("#schedulerReuseBucketHours").value = String(data.reuse_bucket_hours ?? 12);
  setStatus("#collectionStatusNote", "스케줄 설정 저장 완료");
}

function parsePriceToManwon(raw) {
  if (!raw) return null;
  const text = String(raw).replace(/,/g, "").trim();
  const onlyNumbers = text.match(/\d+/g);
  if (!onlyNumbers) return null;
  const numeric = Number(onlyNumbers.join(""));
  return Number.isFinite(numeric) ? numeric : null;
}

function normalizeText(value) {
  return String(value || "").trim().toLowerCase();
}

function flattenLiveWatchRows(groups) {
  const rows = [];
  (groups || []).forEach((group) => {
    const complexNo = group.complex_no;
    const complexName = group.complex_name || "-";

    if (group.error) {
      rows.push({
        complexNo,
        complexName,
        articleNo: "-",
        articleName: "조회 실패",
        tradeType: "-",
        price: "-",
        floorInfo: "-",
        direction: "-",
        error: group.error,
        priceManwon: null,
      });
      return;
    }

    const articles = Array.isArray(group.articles) ? group.articles : [];
    if (!articles.length) {
      rows.push({
        complexNo,
        complexName,
        articleNo: "-",
        articleName: "표시할 매물 없음",
        tradeType: "-",
        price: "-",
        floorInfo: "-",
        direction: "-",
        error: null,
        priceManwon: null,
      });
      return;
    }

    articles.forEach((article) => {
      const price = article.price || "-";
      rows.push({
        complexNo,
        complexName,
        articleNo: article.article_no || "-",
        articleName: article.article_name || "-",
        tradeType: article.trade_type || "-",
        price,
        floorInfo: article.floor_info || "-",
        direction: article.direction || "-",
        error: null,
        priceManwon: parsePriceToManwon(price),
      });
    });
  });
  return rows;
}

function renderLiveWatchListings() {
  const keyword = normalizeText(qs("#liveFilterKeyword").value);
  const tradeTypeKeyword = normalizeText(qs("#liveFilterTradeType").value);
  const maxPriceRaw = qs("#liveFilterMaxPrice").value.trim();
  const maxPrice = maxPriceRaw ? Number(maxPriceRaw) : null;

  const filtered = state.liveWatchRows.filter((row) => {
    const haystack = normalizeText(`${row.complexName} ${row.articleName}`);
    if (keyword && !haystack.includes(keyword)) return false;

    if (tradeTypeKeyword && !normalizeText(row.tradeType).includes(tradeTypeKeyword)) return false;

    if (Number.isFinite(maxPrice) && row.priceManwon != null && row.priceManwon > maxPrice) {
      return false;
    }
    return true;
  });

  const body = qs("#liveWatchBody");
  body.innerHTML = "";
  if (!filtered.length) {
    body.innerHTML = '<tr><td colspan="6" class="muted">표시할 실시간 매물이 없습니다.</td></tr>';
    setStatus("#liveWatchStatus", "조건에 맞는 실시간 매물이 없습니다.");
    return;
  }

  filtered.forEach((row) => {
    const tr = document.createElement("tr");
    if (row.error) {
      tr.innerHTML = `
        <td>${row.complexNo} ${row.complexName}</td>
        <td colspan="5" class="muted">조회 실패: ${row.error}</td>
      `;
      body.appendChild(tr);
      return;
    }

    tr.innerHTML = `
      <td><span class="mono">${row.complexNo}</span> ${row.complexName}</td>
      <td class="mono">${row.articleNo}</td>
      <td>${row.articleName}</td>
      <td>${row.tradeType}</td>
      <td>${row.price}</td>
      <td>${row.floorInfo}${row.direction && row.direction !== "-" ? ` / ${row.direction}` : ""}</td>
    `;
    body.appendChild(tr);
  });

  setStatus("#liveWatchStatus", `실시간 조회 ${state.liveWatchRows.length}건 중 ${filtered.length}건 표시`);
}

function onLiveFilterInput() {
  if (!state.liveWatchRows.length) return;
  renderLiveWatchListings();
}

async function loadLiveWatchComplexes() {
  const page = Number(qs("#liveWatchPage").value || "1");
  const maxPerComplex = Number(qs("#liveWatchMax").value || "10");
  const data = await api(`/me/watch-complexes/live?page=${page}&max_per_complex=${maxPerComplex}`);
  const groups = Array.isArray(data.items) ? data.items : [];
  state.liveWatchRows = flattenLiveWatchRows(groups);

  if (!state.liveWatchRows.length) {
    qs("#liveWatchBody").innerHTML = '<tr><td colspan="6" class="muted">실시간 조회 대상 단지가 없습니다.</td></tr>';
    setStatus("#liveWatchStatus", "실시간 조회 대상 단지가 없습니다.");
    return;
  }

  renderLiveWatchListings();
  setStatus("#watchStatus", `실시간 매물 조회 완료: ${groups.length}개 단지`);
}

async function hydrateWatchDashboard() {
  try {
    await loadWatchComplexes();
  } catch (_e) {
    // ignore initial watch list loading errors in background hydration.
  }
  try {
    await loadLiveWatchComplexes();
  } catch (_e) {
    // ignore initial live loading errors in background hydration.
  }
  try {
    await loadCollectionStatus();
  } catch (_e) {
    // ignore initial collection status loading errors in background hydration.
  }
}

async function ingestNow() {
  const complexNo = Number(qs("#ingestComplexNo").value);
  const { page, maxPages, force } = getIngestOptions();
  const query = new URLSearchParams({
    page: String(page),
    max_pages: String(maxPages),
    force: force ? "true" : "false",
  });
  const data = await api(`/crawler/ingest/${complexNo}?${query.toString()}`, {
    method: "POST",
  });

  const pagesFetched = Number(data.pages_fetched || 0);
  const listingCount = Number(data.listing_count || 0);
  const reused = Number(data.reused || 0) === 1;
  const baseLine = reused
    ? `데이터 재사용: 단지 ${complexNo}는 현재 수집 구간의 기존 데이터 ${listingCount}건을 재사용했습니다.`
    : `데이터 새로고침 완료: 단지 ${complexNo}에서 ${listingCount}건을 수집했습니다.`;
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

function getIngestOptions() {
  const page = Number(qs("#ingestPage").value || "1");
  const maxPages = Number(qs("#ingestMaxPages")?.value || "1");
  const force = Boolean(qs("#ingestForce")?.checked);
  return { page, maxPages, force };
}

async function ingestWatchAll() {
  const { page, maxPages, force } = getIngestOptions();
  const data = await api("/me/watch-complexes/ingest", {
    method: "POST",
    body: JSON.stringify({
      page,
      max_pages: maxPages,
      force,
    }),
  });

  const failed = (data.results || []).filter((item) => item && item.ok === false);
  const failedText = failed.length
    ? ` 실패 예시: ${failed
        .slice(0, 3)
        .map((item) => `${item.complex_no}(${item.error})`)
        .join(", ")}`
    : "";
  setStatus(
    "#ingestStatus",
    `일괄 수집 완료: 대상 ${data.requested_complex_count}개, 성공 ${data.success_count}개, 실패 ${data.failure_count}개, 재사용 ${data.reused_count}개, 총 ${data.total_listing_count}건.${failedText}`
  );
  try {
    await loadCollectionStatus();
  } catch (_err) {
    // ignore collection refresh failure after bulk ingest.
  }
}

async function loadMeta() {
  const data = await api("/meta");
  setStatus(
    "#ingestStatus",
    `운영 정보: interval=${data.crawler_interval_minutes}분, retry=${data.crawler_max_retry}회, reuse_window=${data.crawler_reuse_window_hours}시간. 일반 사용보다는 운영 점검용 정보입니다.`
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
  qs("#notifyInterestTradeType").value = data.interest_trade_type || "ALL";
  qs("#notifyMonthlyConversionRatePct").value =
    data.monthly_rent_conversion_rate_pct == null ? "" : String(data.monthly_rent_conversion_rate_pct);
  state.analyticsTradeType = data.interest_trade_type || "ALL";
  state.analyticsConversionRate = Number(data.resolved_monthly_conversion_rate_pct || 5.1);
  setStatus(
    "#notifyStatus",
    `알림 설정 조회 완료 (관심유형=${state.analyticsTradeType}, 적용 전월세전환율=${state.analyticsConversionRate}%)`
  );
}

async function saveNotificationSettings() {
  const tradeType = qs("#notifyInterestTradeType").value || "ALL";
  const monthlyRateRaw = qs("#notifyMonthlyConversionRatePct").value.trim();
  const monthlyRate = monthlyRateRaw ? Number(monthlyRateRaw) : null;
  const payload = {
    email_enabled: qs("#notifyEmailEnabled").checked,
    email_address: qs("#notifyEmailAddress").value.trim() || null,
    telegram_enabled: qs("#notifyTelegramEnabled").checked,
    telegram_chat_id: qs("#notifyTelegramChatId").value.trim() || null,
    bargain_alert_enabled: qs("#notifyBargainEnabled").checked,
    bargain_lookback_days: Number(qs("#notifyLookbackDays").value || "30"),
    bargain_discount_threshold: Number(qs("#notifyDiscountThreshold").value || "0.08"),
    interest_trade_type: tradeType,
    monthly_rent_conversion_rate_pct: monthlyRate,
    monthly_rent_conversion_rate_use_default: monthlyRateRaw === "",
  };
  const data = await api("/me/notification-settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  state.analyticsTradeType = data.interest_trade_type || "ALL";
  state.analyticsConversionRate = Number(data.resolved_monthly_conversion_rate_pct || 5.1);
  setStatus(
    "#notifyStatus",
    `알림 설정 저장 완료 (관심유형=${state.analyticsTradeType}, 적용 전월세전환율=${state.analyticsConversionRate}%)`
  );
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
  if (!canvas) return;
  if (state[chartStateKey]) {
    state[chartStateKey].destroy();
  }
  state[chartStateKey] = new Chart(canvas.getContext("2d"), config);
}

function renderBargainRows(items) {
  const body = qs("#bargainBody");
  body.innerHTML = "";
  if (!items.length) {
    body.innerHTML = '<tr><td colspan="7" class="muted">조건에 맞는 급매 후보가 없습니다.</td></tr>';
    return;
  }

  items.forEach((item) => {
    const effective =
      item.effective_price_manwon == null ? null : Number(item.effective_price_manwon);
    const priceLabel = item.deal_price_text || "-";
    const priceText = Number.isFinite(effective)
      ? `${priceLabel} (환산 ${Math.round(effective)}만원)`
      : priceLabel;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${item.complex_name || item.complex_no || "-"}</td>
      <td>${item.article_no}</td>
      <td>${item.article_name || "-"}</td>
      <td>${item.trade_type_name || "-"}</td>
      <td>${priceText}</td>
      <td>${Math.round(item.baseline_median_manwon)}</td>
      <td>${(item.discount_rate * 100).toFixed(2)}%</td>
    `;
    body.appendChild(tr);
  });
}

function getAnalyticsPreferences() {
  const tradeType = qs("#notifyInterestTradeType")?.value || state.analyticsTradeType || "ALL";
  const monthlyRateRaw = qs("#notifyMonthlyConversionRatePct")?.value?.trim() || "";
  const monthlyRate = monthlyRateRaw ? Number(monthlyRateRaw) : state.analyticsConversionRate;
  return {
    tradeType,
    monthlyRate: Number.isFinite(monthlyRate) && monthlyRate > 0 ? monthlyRate : 5.1,
  };
}

async function loadTrend() {
  const complexNo = Number(qs("#trendComplexNo").value);
  const days = Number(qs("#trendDays").value || "30");
  const pref = getAnalyticsPreferences();
  const query = new URLSearchParams({
    days: String(days),
    monthly_conversion_rate_pct: String(pref.monthlyRate),
  });
  if (pref.tradeType !== "ALL") {
    query.set("trade_type_name", pref.tradeType);
  }
  const data = await api(`/analytics/trend/${complexNo}?${query.toString()}`);
  const series = Array.isArray(data.series) ? data.series : [];
  const labels = series.map((row) => row.date);
  const values = series.map((row) => row.avg_price_manwon);

  if (!labels.length) {
    if (state.trendChart) {
      state.trendChart.destroy();
      state.trendChart = null;
    }
    setStatus("#trendStatus", "해당 조건에 표시할 시세 데이터가 없습니다.");
    return;
  }

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
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top" } },
    },
  });
  setStatus(
    "#trendStatus",
    `${labels.length}개 시점의 평균 시세 데이터를 표시했습니다. (유형=${data.trade_type_name}, 전환율=${data.monthly_conversion_rate_pct}%)`
  );
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
  const pref = getAnalyticsPreferences();
  query.set("monthly_conversion_rate_pct", String(pref.monthlyRate));
  if (pref.tradeType !== "ALL") {
    query.set("trade_type_name", pref.tradeType);
  }
  complexNos.forEach((no) => query.append("complex_nos", String(no)));

  const data = await api(`/analytics/compare?${query.toString()}`);
  const palette = ["#0ea5e9", "#ef4444", "#16a34a", "#f59e0b", "#475569", "#0891b2"];

  const labelsSet = new Set();
  complexNos.forEach((no) => {
    (data.series[String(no)] || data.series[no] || []).forEach((row) => labelsSet.add(row.date));
  });
  const labels = Array.from(labelsSet).sort();
  if (!labels.length) {
    if (state.compareChart) {
      state.compareChart.destroy();
      state.compareChart = null;
    }
    setStatus("#compareStatus", "비교 가능한 시세 데이터가 없습니다.");
    return;
  }

  const datasets = complexNos.map((no, idx) => {
    const rows = data.series[String(no)] || data.series[no] || [];
    const map = new Map(rows.map((r) => [r.date, r.avg_price_manwon]));
    return {
      label: `단지 ${no}`,
      data: labels.map((label) => map.get(label) ?? null),
      borderColor: palette[idx % palette.length],
      backgroundColor: "transparent",
      spanGaps: true,
      tension: 0.2,
    };
  });

  upsertChart("#compareChart", "compareChart", {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { position: "top" } },
    },
  });
  setStatus(
    "#compareStatus",
    `${complexNos.length}개 단지, ${labels.length}개 시점으로 비교했습니다. (유형=${data.trade_type_name}, 전환율=${data.monthly_conversion_rate_pct}%)`
  );
}

async function loadBargains() {
  const complexNo = Number(qs("#bargainComplexNo").value);
  const lookbackDays = Number(qs("#bargainDays").value || "30");
  const threshold = Number(qs("#bargainThreshold").value || "0.08");
  const pref = getAnalyticsPreferences();
  const query = new URLSearchParams({
    lookback_days: String(lookbackDays),
    discount_threshold: String(threshold),
    monthly_conversion_rate_pct: String(pref.monthlyRate),
  });
  if (pref.tradeType !== "ALL") {
    query.set("trade_type_name", pref.tradeType);
  }
  const data = await api(`/analytics/bargains/${complexNo}?${query.toString()}`);
  renderBargainRows(data.items || []);
  setStatus(
    "#bargainStatus",
    `탐지 완료: 단지 ${complexNo}, 유형 ${data.trade_type_name}, 전환율 ${data.monthly_conversion_rate_pct}%, 기간 ${lookbackDays}일, 기준 ${(threshold * 100).toFixed(1)}%로 ${
      (data.items || []).length
    }건을 찾았습니다.`
  );
}

async function loadMyBargainAlerts() {
  const lookbackDays = Number(qs("#bargainDays").value || "30");
  const threshold = Number(qs("#bargainThreshold").value || "0.08");
  const pref = getAnalyticsPreferences();
  const query = new URLSearchParams({
    lookback_days: String(lookbackDays),
    discount_threshold: String(threshold),
    monthly_conversion_rate_pct: String(pref.monthlyRate),
  });
  if (pref.tradeType !== "ALL") {
    query.set("trade_type_name", pref.tradeType);
  }
  const data = await api(`/me/alerts/bargains?${query.toString()}`);
  renderBargainRows(data.items || []);
  setStatus(
    "#bargainStatus",
    `내 관심단지 전체 탐지 완료: 유형 ${data.trade_type_name}, 전환율 ${data.monthly_conversion_rate_pct || pref.monthlyRate}%, 기간 ${lookbackDays}일, 기준 ${(threshold * 100).toFixed(1)}%, 후보 ${
      (data.items || []).length
    }건입니다.`
  );
}

function bind(id, fn, errorTargets = ["#authStatus", "#ingestStatus"]) {
  const element = qs(id);
  if (!element) return;
  element.addEventListener("click", async () => {
    try {
      await fn();
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      errorTargets.forEach((target) => setStatus(target, message));
    }
  });
}

bind("#registerBtn", register, ["#authStatus"]);
bind("#loginBtn", login, ["#authStatus"]);
bind("#meBtn", me, ["#authStatus"]);
bind("#logoutBtn", logout, ["#authStatus"]);
bind("#searchComplexBtn", searchComplexes, ["#watchStatus"]);
bind("#parseComplexUrlBtn", parseComplexUrl, ["#watchStatus"]);
bind("#addWatchBtn", addWatchComplex, ["#watchStatus"]);
bind("#loadWatchBtn", loadWatchComplexes, ["#watchStatus"]);
bind("#loadLiveWatchBtn", loadLiveWatchComplexes, ["#liveWatchStatus"]);
bind("#loadCollectionStatusBtn", loadCollectionStatus, ["#collectionStatusNote"]);
bind("#loadSchedulerConfigBtn", loadSchedulerConfig, ["#collectionStatusNote"]);
bind("#saveSchedulerConfigBtn", saveSchedulerConfig, ["#collectionStatusNote"]);
bind("#ingestBtn", ingestNow, ["#ingestStatus"]);
bind("#ingestWatchAllBtn", ingestWatchAll, ["#ingestStatus"]);
bind("#metaBtn", loadMeta, ["#ingestStatus"]);
bind("#billingMeBtn", loadBillingMe, ["#billingStatus"]);
bind("#billingCheckoutBtn", startDummyCheckout, ["#billingStatus"]);
bind("#billingCompleteBtn", completeDummyCheckout, ["#billingStatus"]);
bind("#loadNotifyBtn", loadNotificationSettings, ["#notifyStatus"]);
bind("#saveNotifyBtn", saveNotificationSettings, ["#notifyStatus"]);
bind("#dispatchAlertBtn", dispatchAlertNow, ["#notifyStatus"]);
bind("#loadTrendBtn", loadTrend, ["#trendStatus"]);
bind("#loadCompareBtn", loadCompare, ["#compareStatus"]);
bind("#loadBargainBtn", loadBargains, ["#bargainStatus"]);
bind("#loadMyBargainBtn", loadMyBargainAlerts, ["#bargainStatus"]);

qs("#watchComplexKeyword")?.addEventListener("input", onWatchComplexKeywordInput);
qs("#liveFilterKeyword")?.addEventListener("input", onLiveFilterInput);
qs("#liveFilterTradeType")?.addEventListener("input", onLiveFilterInput);
qs("#liveFilterMaxPrice")?.addEventListener("input", onLiveFilterInput);

if (state.token) {
  me()
    .then(() => hydrateWatchDashboard())
    .catch(() => {
      setAuthControls(false);
      renderUserBadge("로그인 필요");
      renderBillingBadge("FREE", "LOGGED_OUT");
    });
} else {
  setAuthControls(false);
  renderBillingBadge("FREE", "LOGGED_OUT");
}
