
// ======= General Setup ========
window.PAGE_LOADED_AT = window.HOSTHUB_CONFIG.pageLoadedAt;
let HAS_NEW_CALLS = false;
let PTR_MODE = "refresh"; // "refresh" | "new_calls"

// ======= Category Tabs ========
const CATEGORY_STYLES = {
  reservation: { bg: "rgba(34, 197, 94, 0.10)", border: "rgba(34, 197, 94, 0.30)", text: "#15803D" },
  carryout: { bg: "rgba(255, 106, 0, 0.10)", border: "rgba(255, 106, 0, 0.28)", text: "#B45309" },
  leave_message: { bg: "rgba(50, 177, 255, 0.10)", border: "rgba(50, 177, 255, 0.30)", text: "#0B5ED7" },
  private_events: { bg: "rgba(124, 58, 237, 0.10)", border: "rgba(124, 58, 237, 0.32)", text: "#6D28D9" },
  handled: { bg: "rgba(148, 163, 184, 0.08)", border: "rgba(148, 163, 184, 0.26)", text: "#64748B" },
};

// ======= Resolve Modal Config =======
const HANDLERS = [
  { value: "david", label: "David" },
  { value: "derek", label: "Derek" },
  { value: "gabriel", label: "Gabriel" },
  { value: "brian", label: "Brian" },
  { value: "miguel", label: "Miguel" },
  {value: "adriana", label: "Adriana"},
];

// Use the SAME keys as your Django model choices
const DISPOSITIONS_BY_CATEGORY = {
reservation: [
  { value: "reservation_placed", label: "Reservation Placed by Host" },
  { value: "reservation_link", label: "Reservation Placed via Link Sent to Caller" },
  { value: "reservation_update", label: "Reservation Successfully Updated by Host" },
  { value: "reservation_canceled", label: "Reservation Canceled by Host" },
  { value: "questions_answered", label: "Caller Had Questions That Were Answered by AI Host" },
  { value: "other", label: "Other" },
],

carryout: [
  { value: "carryout_ai_host", label: "Carryout Order Placed via AI Host" },
  { value: "carryout_link", label: "Carryout Order Placed via Link Sent to Caller" },
  { value: "questions_answered", label: "Caller Had Questions That Were Answered by AI Host" },
  { value: "other", label: "Other" },
],

private_events: [
  { value: "private_party", label: "Informed Manager About Private Party First Inquiry" },
  { value: "private_party_message", label: "Informed Manager About Message Left About Existing Private Party" },
  { value: "questions_answered", label: "Caller Had Questions That Were Answered by AI Host" },
  { value: "other", label: "Other" },
],

leave_message: [
  { value: "message_handled", label: "Message Left by Caller Handled by Host" },
  { value: "other", label: "Other" },
],

default: [
  { value: "questions_answered", label: "Caller Had Questions That Were Answered by AI Host" },
  { value: "other", label: "Other" },
],
};



// ======= General Setup ========

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function renderFinalTranscriptItem(item) {
  const container = document.getElementById("finalTranscriptContainer");
  if (!container) return;

  // Bland: item.user is "assistant" or "user"
  const roleClass = item.user === "assistant" ? "agent-bubble" : "user-bubble";

  const div = document.createElement("div");
  div.className = `transcript-row ${roleClass}`;
  div.dataset.turnId = item.id;

  div.innerHTML = `
    <div class="bubble">
      ${escapeHtml(item.text)}
    </div>
  `;

  container.appendChild(div);
}

function scrollFinalTranscriptToTop() {
  const container = document.getElementById("finalTranscriptContainer");
  if (!container) return;

  requestAnimationFrame(() => {
    container.scrollTop = 0;
  });
}

async function loadFinalTranscriptsForDashboard(callId) {
  const box = document.getElementById("finalTranscriptBox");
  const details = document.getElementById("finalTranscriptDetails");
  const container = document.getElementById("finalTranscriptContainer");
  if (!box || !container) return;

  box.style.display = "block";
  if (details) details.open = false; // starts closed
  container.innerHTML = `<div class="small text-muted">Loading transcript…</div>`;

  try {
    // IMPORTANT: match your Django route:
    // path("transcript/call/<str:call_id>/", ...)
    const res = await fetch(`/test/transcript/call/${callId}/`, {
      headers: { "Accept": "application/json" },
      credentials: "same-origin",
    });

    if (!res.ok) {
      container.innerHTML = `<div class="small text-danger">Failed to load transcript (${res.status})</div>`;
      return;
    }

    const data = await res.json();
    const transcripts = data.transcripts || [];

    container.innerHTML = "";

    if (!transcripts.length) {
      container.innerHTML = `<div class="small text-muted">No transcript available.</div>`;
      return;
    }

    transcripts.forEach(renderFinalTranscriptItem);
    requestAnimationFrame (()=> {
      container.scrollTop = container.scrollHeight;
    })
  } catch (e) {
    console.error("Failed to load final transcripts", e);
    container.innerHTML = `<div class="small text-danger">Error loading transcript.</div>`;
  }
}

function applyCategoryTabStyles() {
  document.querySelectorAll(".tab-navigation .tab-btn").forEach((tab) => {
    const key = tab.dataset.tab;
    const isActive = tab.classList.contains("active");
    const styles = CATEGORY_STYLES[key];

    // Reset (inactive)
    tab.style.backgroundColor = "#FFFFFF";
    tab.style.borderColor = "#E5E7EB";
    tab.style.color = "#374151";
    tab.style.fontWeight = "500";

    // Apply (active)
    if (isActive && styles) {
      tab.style.backgroundColor = styles.bg;
      tab.style.borderColor = styles.border;
      tab.style.color = styles.text;
      tab.style.fontWeight = "600";
    }
  });
}

// ======= Date Filters ========
function handleDateFilterChange(value) {
  if (value === "custom") {
    document.getElementById("customDatePicker").classList.remove("hidden");
    const currentDate = document.getElementById("customDatePicker").value;
    if (currentDate) handleCustomDateChange(currentDate);
  } else {
    document.getElementById("customDatePicker").classList.add("hidden");
    window.location.href = value;
  }
}

function handleCustomDateChange(dateValue) {
  if (!dateValue) return;

  const category = window.HOSTHUB_CONFIG.activeCategory;
  const hostStatus = window.HOSTHUB_CONFIG.activeHostStatus;

  let url = "?date=custom&custom_date=" + dateValue;

  if (hostStatus === "resolved") url += "&host_status=resolved";
  if (category) url += "&category=" + category;

  window.location.href = url;
}

// ======= Helpers ========
function formatPhoneNumber(phone) {
  if (!phone) return "";
  const digits = phone.replace(/\+/g, "").replace(/\D/g, "");
  if (digits.length === 11 && digits.startsWith("1")) {
    return `(${digits.slice(1, 4)}) ${digits.slice(4, 7)}-${digits.slice(7)}`;
  } else if (digits.length === 10) {
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6)}`;
  }
  return phone;
}

// ======= Details Panel Selection ========
function selectCall(element) {
  document.querySelectorAll(".message-item").forEach((item) => item.classList.remove("selected"));
  element.classList.add("selected");

  const call = {
    id: element.dataset.callId,
    callLocation: element.dataset.callLocation || "",
    userName: element.dataset.userName || "",
    fromNumber: element.dataset.fromNumber || "",
    toNumber: element.dataset.toNumber || "",
    category: element.dataset.category || "",
    categoryValue: element.dataset.categoryValue || "",
    summary: element.dataset.summary || "",
    fullTranscript: element.dataset.fullTranscript || "",
    createdAt: element.dataset.createdAt || "",
    duration: parseInt(element.dataset.duration) || 0,
    hostStatus: element.dataset.hostStatus || "",
    notes: element.dataset.notes || "",
    reservationDate: element.dataset.reservationDate || "",
    reservationTime: element.dataset.reservationTime || "",
    reservationGuests: element.dataset.reservationGuests || "",
    reservationRequest: element.dataset.reservationRequest || "",
    orderSummary: element.dataset.orderSummary || "",
    totalPrice: element.dataset.totalPrice || "",
    partyDate: element.dataset.partyDate || "",
    partyTime: element.dataset.partyTime || "",
    partyGuests: element.dataset.partyGuests || "",
    partyOccasion: element.dataset.partyOccasion || "",
    partyMessage: element.dataset.partyMessage || "",
    leaveMessage: element.dataset.leaveMessage || "",
    handledBy: element.dataset.handledBy || "",
    handledByDisplay: element.dataset.handledByDisplay || "",
    handledAt: element.dataset.handledAt || "",
    disposition: element.dataset.disposition || "",
    dispositionDisplay: element.dataset.dispositionDisplay || "",
  };

  document.getElementById("panelTitle").textContent = call.category || "Call Details";

  const customerInfo = document.getElementById("customerInfo");
  const customerName = document.getElementById("customerName");
  const customerPhone = document.getElementById("customerPhone");

  customerName.textContent = call.userName || "Unknown";
  customerPhone.textContent = call.fromNumber ? formatPhoneNumber(call.fromNumber) : "No phone number";
  customerInfo.style.display = "block";

  const handledCheckbox = document.getElementById("handled");
  handledCheckbox.checked = call.hostStatus === "resolved";
  handledCheckbox.dataset.callId = call.id;

  const requestDetailsTitleEl = document.getElementById("requestDetailsTitle");
  let requestTitle = "Request Details";
  if (call.categoryValue === "reservation") requestTitle = "Reservation Request Details";
  else if (call.categoryValue === "carryout") requestTitle = "Carryout Details";
  else if (call.categoryValue === "leave_message") requestTitle = "Message Details";
  requestDetailsTitleEl.textContent = requestTitle;

  const callInfoSection = document.getElementById("callInfoSection");
  const callInfoList = document.getElementById("callInfoList");
  const requestDetailsSection = document.getElementById("requestDetailsSection");
  const requestDetailsList = document.getElementById("requestDetailsList");

  callInfoList.innerHTML = "";
  requestDetailsList.innerHTML = "";

  const callInfo = [
    { label: "Type", value: call.category || "N/A" },
    { label: "Received", value: call.createdAt || "N/A" },
  ];

  if (call.duration) {
    const minutes = Math.floor(call.duration / 60);
    const seconds = call.duration % 60;
    callInfo.push({ label: "Duration", value: `${minutes}m ${seconds}s` });
  }

  if (call.hostStatus === "resolved") {
    if (call.handledByDisplay) callInfo.push({ label: "Handled by", value: call.handledByDisplay });
    if (call.handledAt) {
      const dt = new Date(call.handledAt);
      const pretty = isNaN(dt.getTime())
      ? call.handledAt
      : dt.toLocaleString([], { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
      callInfo.push({ label: "Handled at", value: pretty });

    }
    if (call.dispositionDisplay) callInfo.push({ label: "Host Action", value: call.dispositionDisplay });
  }


  callInfo.forEach((detail) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${detail.label}:</strong> ${detail.value}`;
    callInfoList.appendChild(li);
  });
  callInfoSection.style.display = "block";

  const requestDetails = [];

  if (call.categoryValue === "reservation") {
    if (call.userName) requestDetails.push({ label: "Name", value: call.userName });
    if (call.reservationGuests) requestDetails.push({ label: "Guests", value: call.reservationGuests });
    if (call.reservationDate) requestDetails.push({ label: "Reservation date", value: call.reservationDate });
    if (call.reservationTime) requestDetails.push({ label: "Reservation time", value: call.reservationTime });
    if (call.reservationRequest) requestDetails.push({label: "Request", value: call.reservationRequest});
    if (call.leaveMessage) requestDetails.push({ label: "Update Request", value: call.leaveMessage });
  }

  if (call.categoryValue === "private_events") {
    if (call.userName) requestDetails.push({ label: "Name", value: call.userName });
    if (call.partyOccasion) requestDetails.push({ label: "Ocassion", value: call.partyOccasion });
    if (call.partyDate) requestDetails.push({ label: "Date", value: call.partyDate });
    if (call.partyTime) requestDetails.push({ label: "Time", value: call.partyTime });
    if (call.partyGuests) requestDetails.push({ label: "Guests", value: call.partyGuests });
    if (call.partyMessage) requestDetails.push({ label: "User Message", value: call.partyMessage });
    if (call.leaveMessage) requestDetails.push({ label: "User Message", value: call.leaveMessage });
  }

  if (call.categoryValue === "carryout") {
    if (call.orderSummary) {
      const items = call.orderSummary
        .split(";")
        .map((i) => i.trim())
        .filter(Boolean);

      requestDetails.push({ label: "Order summary", value: items });
    }

    if (call.totalPrice) requestDetails.push({ label: "Total price", value: `$${call.totalPrice}` });
  }

  if (call.categoryValue === "leave_message") {
    if (call.leaveMessage) requestDetails.push({ label: "User Message", value: call.leaveMessage});
  }

  if (requestDetails.length > 0) {
    requestDetails.forEach((detail) => {
      const li = document.createElement("li");

      if (Array.isArray(detail.value)) {
        li.innerHTML = `<strong>${detail.label}:</strong>`;
        const ul = document.createElement("ul");
        ul.style.margin = "6px 0 0 18px";
        ul.style.padding = "0";

        detail.value.forEach((item) => {
          const itemLi = document.createElement("li");
          itemLi.textContent = item;
          itemLi.style.marginBottom = "4px";
          ul.appendChild(itemLi);
        });

        li.appendChild(ul);
      } else {
        li.innerHTML = `<strong>${detail.label}:</strong> ${detail.value}`;
      }

      requestDetailsList.appendChild(li);
    });

    requestDetailsSection.style.display = "block";
  } else {
    requestDetailsSection.style.display = "none";
  }

  loadFinalTranscriptsForDashboard(call.id);
}

// ======= CSRF + Status Update ========
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + "=") {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}

function getCSRFToken() {
  const metaTag = document.querySelector('meta[name="csrf-token"]');
  if (metaTag) return metaTag.getAttribute("content");
  return getCookie("csrftoken");
}

function createCheckIcon() {
  const icon = document.createElement("span");
  icon.className = "check-icon";
  icon.textContent = "✓";
  return icon;
}

// Open Date Modal
function openCustomDate() {
  document.getElementById("customDateModal").style.display = "flex";
}
function closeCustomDate() {
  document.getElementById("customDateModal").style.display = "none";
}

// optional: close when clicking outside the card
document.addEventListener("click", function (e) {
  const modal = document.getElementById("customDateModal");
  if (!modal || modal.style.display !== "flex") return;
  if (e.target === modal) closeCustomDate();
});

let resolveModalInstance = null;
let resolveModalSaved = false;

function getSelectedCallItem() {
  return document.querySelector('.message-item.selected');
}

function populateSelect(selectEl, options, selectedValue = "") {
  selectEl.innerHTML = "";
  options.forEach(opt => {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    if (selectedValue && selectedValue === opt.value) o.selected = true;
    selectEl.appendChild(o);
  });
}

function openResolveModal(callId, source /* "details"|"list" */, callItemEl = null) {
  const modalEl = document.getElementById("resolveCallModal");
  const handledBySelect = document.getElementById("handledBySelect");
  const dispositionSelect = document.getElementById("dispositionSelect");
  const dispositionHint = document.getElementById("dispositionHint");

  document.getElementById("resolveModalCallId").value = callId;
  document.getElementById("resolveModalSource").value = source;

  // defaults
  const lastHandler = localStorage.getItem("hosthub_last_handler") || "";
  populateSelect(handledBySelect, HANDLERS, lastHandler || HANDLERS[0].value);

  // choose dispositions based on category
  const el = callItemEl || getSelectedCallItem();
  const categoryValue = el?.dataset?.categoryValue || "";
  const dispositionOptions = DISPOSITIONS_BY_CATEGORY[categoryValue] || DISPOSITIONS_BY_CATEGORY.default;

  populateSelect(dispositionSelect, dispositionOptions, dispositionOptions[0]?.value || "");
  if (dispositionHint) {
    dispositionHint.textContent = categoryValue
      ? `Disposition options for: ${categoryValue.replaceAll("_", " ")}`
      : "";
  }

  if (!resolveModalInstance) {
    resolveModalInstance = new bootstrap.Modal(modalEl, { backdrop: "static" });
    // If user closes modal without saving, revert checkbox
    modalEl.addEventListener("hidden.bs.modal", () => {
      const callIdNow = document.getElementById("resolveModalCallId").value;
      const sourceNow = document.getElementById("resolveModalSource").value;

      if (!resolveModalSaved) revertHandledCheckboxUI(callIdNow, sourceNow);
      resolveModalSaved = false;
    });
  }

  resolveModalSaved = false;
  resolveModalInstance.show();
}

function revertHandledCheckboxUI(callId, source) {
  if (source === "details") {
    const detailsCheckbox = document.getElementById("handled");
    if (detailsCheckbox && detailsCheckbox.dataset.callId === String(callId)) {
      detailsCheckbox.checked = false;
    }
  } else {
    // list checkbox for that call
    const listCheckbox = document.querySelector(`article[data-call-id="${callId}"] .checkbox`);
    if (listCheckbox) listCheckbox.checked = false;
  }
}

function handleMarkAsHandled(checked) {
  const callId = document.getElementById("handled").dataset.callId;
  if (!callId) return;
  if (checked) {
    const selected = getSelectedCallItem();
    openResolveModal(callId, "details", selected);
  } else {
    updateCallStatus(callId, "unresolve", null, null, false);
  }
}

function updateCallStatus(callId, action, handledBy = null, disposition=null, fromDetailsPanel = false) {
  const csrfToken = getCSRFToken();
  const formData = new FormData();
  formData.append("action", action);
  formData.append("csrfmiddlewaretoken", csrfToken);

  if (handledBy) formData.append("handled_by", handledBy);
  if (disposition) formData.append("disposition", disposition);

  fetch(`/calls/${callId}/mark-handled/`, {
    method: "POST",
    body: formData,
    headers: { "X-CSRFToken": csrfToken },
  })
    .then((response) => response.json())
    .then((data) => {
      if (!data.success) throw new Error(data.error || "Unknown error");

      const callItem = document.querySelector(`[data-call-id="${callId}"]`);
      if (callItem) {
        if (data.status === "resolved") {
          callItem.classList.add("resolved");
          callItem.dataset.hostStatus = "resolved";

          callItem.dataset.handledBy = data.handled_by || "";
          callItem.dataset.handledByDisplay = data.handled_by_display || "";
          callItem.dataset.handledAt = data.handled_at || "";
          callItem.dataset.disposition = data.disposition || "";
          callItem.dataset.dispositionDisplay = data.disposition_display || "";
                
          const checkbox = callItem.querySelector(".checkbox");
          if (checkbox) checkbox.replaceWith(createCheckIcon());
          
          const statusSpan = callItem.querySelector(".message-status");
          const handler = data.handled_by_display;
          const handledAt = data.handled_at;
          if (statusSpan) {
            if (handler && handledAt) {
              const time = new Date(handledAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
              statusSpan.textContent = `Handled by ${handler} · ${time}`;
            } else if (handler) {
              statusSpan.textContent = `Handled by ${handler}`;
            } else {
              statusSpan.textContent = "Resolved";
            }
          }

          const needsActionTag = callItem.querySelector(".needs-action-tag");
          if (needsActionTag) needsActionTag.style.display = "none";
        } else {
          callItem.classList.remove("resolved");
          callItem.dataset.hostStatus = "needs_action";

          const checkIcon = callItem.querySelector(".check-icon");
          if (checkIcon) {
            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.className = "checkbox";
            checkbox.id = `msg${callId}`;
            checkbox.setAttribute("aria-label", "Mark as complete");
            checkbox.onclick = function (e) {
              e.stopPropagation();
            };
            checkbox.onchange = handleListCheckboxChange;
            checkIcon.replaceWith(checkbox);
          }

          const statusSpan = callItem.querySelector(".message-status");
          if (statusSpan) {
            const userName = callItem.dataset.userName || "";
            statusSpan.textContent = userName || "Guest";
          }

          const categoryValue = callItem.dataset.categoryValue;
          if (categoryValue === "carryout" || categoryValue === "private events" || categoryValue === "reservation") {
            let needsActionTag = callItem.querySelector(".needs-action-tag");
            if (!needsActionTag) {
              needsActionTag = document.createElement("span");
              needsActionTag.className = "needs-action-tag";
              needsActionTag.textContent = "Needs Action";
              const categoryDiv = callItem.querySelector(".message-category");
              if (categoryDiv && categoryDiv.nextSibling) {
                categoryDiv.parentNode.insertBefore(needsActionTag, categoryDiv.nextSibling);
              } else if (categoryDiv) {
                categoryDiv.parentNode.appendChild(needsActionTag);
              }
            } else {
              needsActionTag.style.display = "inline-block";
            }
          }
        }
      }

      const detailsCheckbox = document.getElementById("handled");
      if (detailsCheckbox && detailsCheckbox.dataset.callId === callId) {
        detailsCheckbox.checked = data.status === "resolved";
        const detailsList = document.getElementById("callInfoList");
        if (detailsList) {
          const statusItem = Array.from(detailsList.querySelectorAll("li")).find((li) => li.textContent.includes("Status:"));
          if (statusItem) {
            statusItem.innerHTML = `<strong>Status:</strong> ${data.status === "resolved" ? "Resolved" : "Needs Action"}`;
          }
        }
      }
      if (callItem && callItem.classList.contains("selected")) {
        selectCall(callItem);
      }
    })
    .catch((error) => {
      console.error("Error updating call status:", error);
      alert("Error updating call status. Please try again.");

      const detailsCheckbox = document.getElementById("handled");
      if (fromDetailsPanel && detailsCheckbox && detailsCheckbox.dataset.callId === callId) {
        detailsCheckbox.checked = !detailsCheckbox.checked;
      }
      const listCheckbox = document.querySelector(`article[data-call-id="${callId}"] .checkbox`);
      if (listCheckbox) listCheckbox.checked = !listCheckbox.checked;
    });
}

function handleListCheckboxChange(event) {
  event.stopPropagation();
  const callItem = this.closest("article");
  const callId = callItem.dataset.callId;
  if (this.checked) {
    openResolveModal(callId, "list", callItem);
  } else {
    updateCallStatus(callId, "unresolve", null, null, false);
  }
}

function initListCheckboxes() {
  document.querySelectorAll(".message-item .checkbox").forEach((cb) => {
    cb.onchange = handleListCheckboxChange;
  });
}

// ======= Live Alerts (as-is) ========
let liveAlertTimer = null;
let lastAlertId = null;
let currentAlertId = null;

function getAlertPollUrl() {
  return "/test/live/alerts/";
}

function renderLiveAlert(alert) {
  const banner = document.getElementById("liveAlertBanner");
  const titleEl = document.getElementById("liveAlertTitle");
  const subEl = document.getElementById("liveAlertSub");

  if (!alert) {
    banner.classList.add("hidden");
    lastAlertId = null;
    currentAlertId = null;
    return;
  }

  banner.classList.remove("hidden");
  currentAlertId = alert.id || null;

  const reason = alert.reason_code || "Alert";
  const phoneRaw = alert.from_number || alert.phone_number || "";
  const phone = phoneRaw ? formatPhoneNumber(phoneRaw) : "Unknown number";

  titleEl.textContent = `Live call alert: ${reason}`;
  subEl.textContent = `From: ${phone}`;
}

function resolveCurrentAlert() {
  if (!currentAlertId) {
    renderLiveAlert(null);
    return;
  }

  const csrfToken = getCSRFToken();

  fetch(`/test/live/alerts/${currentAlertId}/resolve/`, {
    method: "POST",
    headers: { "X-CSRFToken": csrfToken, Accept: "application/json" },
  })
    .then((res) => res.json())
    .then(() => renderLiveAlert(null))
    .catch((err) => {
      console.error("resolve alert failed:", err);
      alert("Could not mark as handled. Try again.");
    });
}

function pollLiveAlerts() {
  fetch(getAlertPollUrl(), { method: "GET", headers: { Accept: "application/json" } })
    .then(async (res) => {
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`HTTP ${res.status} - ${text.slice(0, 200)}`);
      }
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      if (!ct.includes("application/json")) {
        const text = await res.text();
        throw new Error(`Expected JSON but got ${ct} - ${text.slice(0, 200)}`);
      }
      return res.json();
    })
    .then((data) => {
      const alerts = data.alerts || [];
      if (!alerts.length) {
        renderLiveAlert(null);
        return;
      }
      const top = alerts[0];
      if (top && top.id && top.id === lastAlertId) return;
      lastAlertId = top?.id ?? null;
      renderLiveAlert(top);
    })
    .catch((err) => {
      console.error("Live alert polling failed:", err);
    });
}

function startLiveAlertPolling() {
  if (liveAlertTimer) return;
  pollLiveAlerts();
  liveAlertTimer = setInterval(pollLiveAlerts, 2000);
}

// ======= New Calls Pill ========
function showNewCallsPill() {
  document.getElementById("newCallsPill")?.classList.remove("hidden");
}

function hideNewCallsPill() {
  document.getElementById("newCallsPill")?.classList.add("hidden");
}

function pollNewCalls() {
  fetch(`/api/new-calls-boolean/?page_loaded_at=${encodeURIComponent(window.PAGE_LOADED_AT)}`)
    .then((res) => res.json())
    .then((data) => {
      console.log("New calls poll data:", data);
      if (data.has_new) showNewCallsPill();
    })
    .catch(console.error);
}

// ======= Live Calls ========
const LIVE_CALLS_ENDPOINT = "/api/bland/live-calls/";
let LAST_LIVE_CALLS = [];
let ACTIVE_TRANSCRIPT_CALL = null;
let ACTIVE_TRANSCRIPT_PANEL = null;
let LIVE_TRANSCRIPT_ES = null;

function getLiveCallPanels() {
  return [
    document.getElementById("liveCallsPanel"),
    document.getElementById("mobileLiveCallsPanel"),
  ].filter(Boolean);
}

function getLiveCallCountElements() {
  return [
    document.getElementById("liveCallsCount"),
    document.getElementById("mobileLiveCallsCount"),
  ].filter(Boolean);
}

function getLiveCallButtons() {
  return [
    document.getElementById("liveCallsBtn"),
    document.querySelector("mobileLiveCallsBtn"),
  ].filter(Boolean);
}

function setLiveCallCounts(count) {
  getLiveCallCountElements().forEach((el) => {
    el.textContent = String(count);
  });
}

function setLiveCallButtonsState(hasLive) {
  getLiveCallButtons().forEach((btn) => {
    btn.classList.toggle("has-live", hasLive);
  });
}

function getLiveCallsPanelHTML(calls) {
  if (!calls || calls.length === 0) {
    return `<div class="live-calls-empty">No live calls at the moment.</div>`;
  }

  return calls
    .map((c) => {
      const id = c.call_id || "unknown";
      const from = c.from ? formatPhoneNumber(c.from) : "Unknown";
      const status = c.status || "unknown";

      return `
        <div class="call-card" data-call-id="${id}">
          <div>
            <div><strong>${from}</strong></div>
            <div class="call-status small text-muted">${status}</div>
          </div>

          <div class="d-flex gap-2">
            <button
              class="transfer-btn btn btn-sm btn-outline-secondary"
              data-call-id="${id}">
              Transfer
            </button>
          </div>
        </div>
      `;
    })
    .join("");
}

function bindLiveCallPanelEvents(panel) {
  panel.querySelectorAll(".call-card").forEach((card) => {
    card.addEventListener("click", (e) => {
      if (e.target.closest(".transfer-btn")) return;
      const callId = card.dataset.callId;
      openTranscriptView(callId, panel);
    });
  });
}

function renderLiveCallsPanel(calls) {
  const panels = getLiveCallPanels();
  if (!panels.length) return;

  const html = getLiveCallsPanelHTML(calls);

  panels.forEach((panel) => {
    panel.innerHTML = html;
    bindLiveCallPanelEvents(panel);
  });
}

function openTranscriptView(callId, panel) {
  if (!panel) return;

  ACTIVE_TRANSCRIPT_CALL = callId;
  ACTIVE_TRANSCRIPT_PANEL = panel;

  panel.innerHTML = `
    <div class="transcript-header d-flex justify-content-between align-items-center mb-2">
      <button class="back-to-live-calls btn btn-sm btn-outline-secondary">← Back</button>
      <div class="small text-muted">${callId}</div>
    </div>

    <div class="live-transcript-container"></div>
  `;

  panel.querySelector(".back-to-live-calls")?.addEventListener("click", () => {
    closeTranscriptSSE();
    ACTIVE_TRANSCRIPT_CALL = null;
    ACTIVE_TRANSCRIPT_PANEL = null;
    renderLiveCallsPanel(LAST_LIVE_CALLS);
  });

  loadTranscriptHistory(callId, panel);
  openTranscriptSSE(callId, panel);
}

async function loadTranscriptHistory(callId, panel) {
  try {
    const res = await fetch(`/test/api/calls/${callId}/turns/?limit=200`);
    const data = await res.json();

    const container = panel?.querySelector(".live-transcript-container");
    if (!container) return;

    container.innerHTML = "";
    (data.turns || []).forEach((turn) => renderTranscriptTurn(turn, panel));
    container.scrollTop = container.scrollHeight;
  } catch (e) {
    console.error("Failed to load transcript history", e);
  }
}

function renderTranscriptTurn(turn, panel) {
  const container = panel?.querySelector(".live-transcript-container");
  if (!container) return;

  const roleClass = turn.role === "agent" ? "agent-bubble" : "user-bubble";

  const div = document.createElement("div");
  div.className = `transcript-row ${roleClass}`;
  div.dataset.seq = turn.sequence;

  div.innerHTML = `
    <div class="bubble">
      ${turn.text}
    </div>
  `;

  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

function openTranscriptSSE(callId, panel) {
  closeTranscriptSSE();

  LIVE_TRANSCRIPT_ES = new EventSource(
    `/test/sse/call/${callId}/?token=${window.HOSTHUB_CONFIG.sseToken}`
  );

  LIVE_TRANSCRIPT_ES.addEventListener("turn", (evt) => {
    const turn = JSON.parse(evt.data);

    const existing = panel?.querySelector(
      `.transcript-row[data-seq="${turn.sequence}"]`
    );
    if (existing) return;

    renderTranscriptTurn(turn, panel);
  });

  LIVE_TRANSCRIPT_ES.onerror = () => {
    console.log("SSE reconnecting...");
  };
}

function closeTranscriptSSE() {
  if (LIVE_TRANSCRIPT_ES) {
    LIVE_TRANSCRIPT_ES.close();
    LIVE_TRANSCRIPT_ES = null;
  }
}

async function pollLiveCalls() {
  try {
    const res = await fetch(LIVE_CALLS_ENDPOINT, { credentials: "same-origin" });
    const data = await res.json();

    console.log("Live calls API response:", data);
    console.log("Calls array:", data.calls);
    if (data.calls && data.calls.length > 0) {
      console.log("First call object:", data.calls[0]);
    }

    if (!data || !data.ok) {
      LAST_LIVE_CALLS = [];
      setLiveCallCounts(0);
      setLiveCallButtonsState(false);

      if (!ACTIVE_TRANSCRIPT_CALL) {
        renderLiveCallsPanel([]);
      }

      return;
    }

    const count = data.count || 0;
    LAST_LIVE_CALLS = data.calls || [];

    if (!ACTIVE_TRANSCRIPT_CALL) {
      renderLiveCallsPanel(LAST_LIVE_CALLS);
    }

    setLiveCallCounts(count);
    setLiveCallButtonsState(count > 0);
  } catch (e) {
    console.error("pollLiveCalls failed:", e);

    LAST_LIVE_CALLS = [];
    setLiveCallCounts(0);
    setLiveCallButtonsState(false);

    if (!ACTIVE_TRANSCRIPT_CALL) {
      renderLiveCallsPanel([]);
    }
  }
}

// ======= Transfer Call ========
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".transfer-btn");
  if (!btn) return;

  const callId = btn.dataset.callId;
  btn.disabled = true;
  btn.textContent = "Transferring…";

  try {
    const res = await fetch("/api/bland/transfer-call/", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": window.HOSTHUB_CONFIG.csrfToken,
      },
      body: new URLSearchParams({ call_id: callId }),
    });

    const data = await res.json();

    if (!data.ok) throw new Error(data.error || "Transfer failed");

    btn.textContent = "Transferred";
  } catch (err) {
    btn.disabled = false;
    btn.textContent = "Transfer";
    alert(err.message);
  }
});



// ======= Init ========
document.addEventListener("DOMContentLoaded", function () {
    applyCategoryTabStyles();
    initListCheckboxes();

    const firstCall = document.querySelector('.message-item[data-call-id]');
    if (firstCall) {
        selectCall(firstCall);
    }

    const closeBtn = document.getElementById("liveAlertClose");
    if (closeBtn) closeBtn.addEventListener("click", resolveCurrentAlert);

    const pill = document.getElementById("newCallsPill");
    if (pill) pill.addEventListener("click", () => {
        pill.textContent = "Refreshing…";
        window.location.href = "?date=today";
    });

    const details = document.getElementById("finalTranscriptDetails");
    const container = document.getElementById("finalTranscriptContainer");
    const transcriptBox = document.getElementById("finalTranscriptBox");

    if (details && container && transcriptBox) {
      details.addEventListener("toggle", () => {
        if (details.open) {
          scrollFinalTranscriptToTop();
        }
      });


    }
    const saveBtn = document.getElementById("saveResolveBtn");
    if (!saveBtn) return;

    saveBtn.addEventListener("click", () => {
      const callId = document.getElementById("resolveModalCallId").value;
      const source = document.getElementById("resolveModalSource").value;
      const handledBy = document.getElementById("handledBySelect").value;
      const disposition = document.getElementById("dispositionSelect").value;

      if (!handledBy) {
        alert("Please select who handled the call.");
        return;
      }
      if (!disposition) {
        alert("Please select a disposition.");
        return;
      }

      localStorage.setItem("hosthub_last_handler", handledBy);

      resolveModalSaved = true;
      resolveModalInstance.hide();

      updateCallStatus(callId, "resolve", handledBy, disposition, source === "details");
    });

  // startLiveAlertPolling();
  // initPullToRefreshOnCallsList();

  // Poll for new calls
    setInterval(pollNewCalls, 5000);
    pollLiveCalls();
    setInterval(pollLiveCalls, 4000);
});
