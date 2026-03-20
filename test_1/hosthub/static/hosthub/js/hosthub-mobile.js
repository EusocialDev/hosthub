// FILTESR JS //
function getMobileShell() {
    return document.querySelector('.mobile-shell');
}

function openMobileFilters() {
const shell = getMobileShell();
if (!shell) return;

shell.classList.add('filters-open');
document.body.classList.add('mobile-sheet-open');
}

function closeMobileFilters() {
const shell = getMobileShell();
if (!shell) return;

shell.classList.remove('filters-open');
document.body.classList.remove('mobile-sheet-open');
}

function applyMobileFilters() {
const category = document.getElementById('mobileCategoryFilter')?.value || '';
const hostStatus = document.getElementById('mobileStatusFilter')?.value || '';
const date = document.getElementById('mobileDateFilter')?.value || 'today';
const customDate = document.getElementById('mobileCustomDate')?.value || '';

if (date === 'custom' && !customDate) {
    return;
}

const params = new URLSearchParams();

if (hostStatus) params.set('host_status', hostStatus);
if (category) params.set('category', category);
if (date) params.set('date', date);

if (date === 'custom') {
    params.set('custom_date', customDate);
}

closeMobileFilters();
window.location.search = params.toString();
}

// LIVE CALL PANEL JS //
function openMobileLiveCalls() {
    const shell = document.querySelector('.mobile-shell');
    if (!shell) return;

    shell.classList.add('live-open');
    document.body.classList.add('mobile-sheet-open');
}

function closeMobileLiveCalls() {
    const shell = document.querySelector('.mobile-shell');
    if (!shell) return;

    shell.classList.remove('live-open');

    if (!shell.classList.contains('filters-open')) {
      document.body.classList.remove('mobile-sheet-open');
    }
}

function getMobileCallData(card) {
    return {
        id: card.dataset.callId || "",
        userName: card.dataset.userName || "",
        fromNumber: card.dataset.fromNumber || "",
        toNumber: card.dataset.toNumber || "",
        category: card.dataset.category || "",
        categoryValue: card.dataset.categoryValue || "",
        summary: card.dataset.summary || "",
        fullTranscript: card.dataset.fullTranscript || "",
        createdAt: card.dataset.createdAt || "",
        duration: parseInt(card.dataset.duration) || 0,
        hostStatus: card.dataset.hostStatus || "",
        notes: card.dataset.notes || "",
        reservationDate: card.dataset.reservationDate || "",
        reservationTime: card.dataset.reservationTime || "",
        reservationGuests: card.dataset.reservationGuests || "",
        orderSummary: card.dataset.orderSummary || "",
        totalPrice: card.dataset.totalPrice || "",
        partyDate: card.dataset.partyDate || "",
        partyTime: card.dataset.partyTime || "",
        partyGuests: card.dataset.partyGuests || "",
        partyOccasion: card.dataset.partyOccasion || "",
        partyMessage: card.dataset.partyMessage || "",
        leaveMessage: card.dataset.leaveMessage || "",
        handledBy: card.dataset.handledBy || "",
        handledByDisplay: card.dataset.handledByDisplay || "",
        handledAt: card.dataset.handledAt || "",
        disposition: card.dataset.disposition || "",
        dispositionDisplay: card.dataset.dispositionDisplay || "",
    };
}

function buildMobileRequestDetails(call) {
    const requestDetails = [];
    if (call.categoryValue === 'reservation') {
        if (call.userName) requestDetails.push({ label: "Name", value: call.userName });
        if (call.reservationGuests) requestDetails.push({ label: "Guests", value: call.reservationGuests });
        if (call.reservationDate) requestDetails.push({ label: "Reservation date", value: call.reservationDate });
        if (call.reservationTime) requestDetails.push({ label: "Reservation time", value: call.reservationTime });
        if (call.leaveMessage) requestDetails.push({ label: "Update Request", value: call.leaveMessage });
    }

    if (call.categoryValue === 'private_events') {
        if (call.userName) requestDetails.push({ label: "Name", value: call.userName });
        if (call.partyOccasion) requestDetails.push({ label: "Occasion", value: call.partyOccasion });
        if (call.partyDate) requestDetails.push({ label: "Date", value: call.partyDate });
        if (call.partyTime) requestDetails.push({ label: "Time", value: call.partyTime });
        if (call.partyGuests) requestDetails.push({ label: "Guests", value: call.partyGuests });
        if (call.partyMessage) requestDetails.push({ label: "User Message", value: call.partyMessage });
        if (call.leaveMessage) requestDetails.push({ label: "User Message", value: call.leaveMessage });
    }

    if (call.categoryValue === 'carryout') {
        if (call.orderSummary) {
            const items = call.orderSummary
              .split(";")
              .map(i => i.trim())
              .filter(Boolean);
      
            requestDetails.push({ label: "Order summary", value: items });
          }
      
          if (call.totalPrice) {
            requestDetails.push({ label: "Total price", value: `$${call.totalPrice}` });
          }
        }
      
        if (call.categoryValue === "leave_message") {
          if (call.leaveMessage) {
            requestDetails.push({ label: "User Message", value: call.leaveMessage });
          }
    }
    return requestDetails;
}

function getMobileRequestDetailsTitle(categoryValue){
    if(categoryValue === 'reservation') return "Reservation Request details";
    if(categoryValue === 'private_events') return "Private Event details";
    if(categoryValue === 'carryout') return "Carryout details";
    if(categoryValue === 'leave_message') return "Message details";
    return "Request details";
}

function formatMobileCategory (value) {
    if (!value) return "-";
    return value.replaceAll("_", " ").replace(/\b\w/g, c => c.toUpperCase());
}

function mobileRenderFinalTranscriptItem(item) {
  const container = document.getElementById("mobileTranscriptContainer");
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


async function loadMobileFinalTranscript(callId) {
  const container = document.getElementById("mobileTranscriptContainer");
  if (!container) return;

  try{
    const res = await fetch(`/test/transcript/call/${callId}/`, {
      headers: {"Accept":"application/json"},
      credentials: "same-origin"
    });

    if (!res.ok) {
      container.innerHTML = `<div class="small text-danger"> Failed to Load Transcripts (${res.status})</div>`;
      return;
    }

    const data = await res.json();
    const transcripts = data.transcripts || [];

    container.innerHTML = '';

    if (!transcripts.length) {
      container.innerHTML = `<div class="small text-muted"> No transcript available.</div>`;
      return;
    }

    transcripts.forEach(mobileRenderFinalTranscriptItem);

  } catch (e) {
    console.error('Failed to load transcript', e);
    container.innerHTML = `<div class="small text-danger">Error loading transcripts.</div>`;
  }
}

function selectMobileCall(card) {
    const shell = document.querySelector('.mobile-shell');
    const detailsView = document.querySelector('.mobile-details-view');

    if (!shell || !detailsView) return;
    const call = getMobileCallData(card);
    const requestDetails = buildMobileRequestDetails(call);
    const requestTitle = getMobileRequestDetailsTitle(call.categoryValue);

    detailsView.innerHTML = `
      <div class="mobile-details-header">
        <button class="mobile-details-back-btn" type="button" onclick="closeMobileDetails()">← Back</button>
  
        <div class="mobile-details-header-text">
          <div class="mobile-details-title">${call.userName || 'Guest'} • ${formatMobileCategory(call.categoryValue)}</div>
          <div class="mobile-details-subtitle">${call.createdAt || ''}</div>
        </div>
      </div>
  
      <div class="mobile-details-content">
        <section class="mobile-details-block">
        <h3>Call Info</h3>
        <ul class="mobile-details-list" id="mobileCallInfoList"></ul>
        </section>
  

        <section class="mobile-details-block" id="mobileRequestDetailsSection">
            <h3 id="mobileRequestDetailsTitle">${requestTitle}</h3>
            <ul class="mobile-details-list" id="mobileRequestDetailsList"></ul>
        </section>
  
        <section class="mobile-details-block">
          <h3>Call Transcript</h3>
          <div class="mobile-transcript-box" id="mobileTranscriptContainer">
            <div class="small text-muted">Loading transcript…</div>
          </div>
        </section>
      </div>
  
      <div class="mobile-details-actions">
        <button class="mobile-mark-handled-btn" type="button">
          Mark as Handled
        </button>
      </div>
    `;


    const mobileCallInfoList = document.getElementById("mobileCallInfoList");
    const mobileRequestDetailsList = document.getElementById("mobileRequestDetailsList");
    const mobileRequestDetailsSection = document.getElementById("mobileRequestDetailsSection");

    const callInfo = [
        { label: "Phone", value: call.fromNumber || "Unknown" },
        { label: "Type", value: call.category || "Unknown" },
        { label: "Received", value: call.createdAt || "—" },
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
            : dt.toLocaleString([], {
                month: "short",
                day: "numeric",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit"
              });
    
          callInfo.push({ label: "Handled at", value: pretty });
    }
    
    if (call.dispositionDisplay) {
          callInfo.push({ label: "Host Action", value: call.dispositionDisplay });
        }
    }
    
    callInfo.forEach((detail) => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${detail.label}:</strong> ${detail.value}`;
        mobileCallInfoList.appendChild(li);
    });
    
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
    
          mobileRequestDetailsList.appendChild(li);
        });
    } else {
        mobileRequestDetailsSection.style.display = "none";
    }
    
    loadMobileFinalTranscript(call.id);
    shell.classList.add('details-open');

}

function closeMobileDetails() {
    const shell = document.querySelector('.mobile-shell');
    const detailsView = document.querySelector('.mobile-details-view');
    if (!shell || !detailsView) return;
  
    shell.classList.remove('details-open');
    detailsView.innerHTML = '';
}

document.addEventListener('DOMContentLoaded', function () {
const mobileDateFilter = document.getElementById('mobileDateFilter');
const mobileCustomDateWrap = document.getElementById('mobileCustomDateWrap');

if (mobileDateFilter && mobileCustomDateWrap) {
    mobileDateFilter.addEventListener('change', function () {
    mobileCustomDateWrap.style.display = this.value === 'custom' ? 'block' : 'none';
    });
}
});

