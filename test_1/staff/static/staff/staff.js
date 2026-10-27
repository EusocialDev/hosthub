function toggleOverrideHours(checkbox) {
    const form = checkbox.closest('form');
    const hoursDiv = form.querySelector('.staff-override-hours');
    if (!hoursDiv) return;
    hoursDiv.style.display = checkbox.checked ? 'none' : 'flex';
}

function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            // Does this cookie string begin with the name we want?
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function getSelectedLocationSlug() {
    const hiddenLocation = document.getElementById('selected-location-slug');
    if (hiddenLocation) {
        return hiddenLocation.value;
    }

    const select = document.getElementById('location-select');
    if (select) {
        return select.value;
    }

    return '';
}

function showStoreStatusMessage(message, isError=false) {
    const messageBox = document.getElementById('store-status-message');

    if (!messageBox) return;

    messageBox.textContent = message;
    messageBox.className = isError
    ? 'store-status-message error'
    : 'store-status-message success';
}

function setButtonsDisabled(disabled) {
    const openBtn = document.getElementById("open-btn");
    const closeBtn = document.getElementById("close-btn");

    if (openBtn) openBtn.disabled = disabled;
    if (closeBtn) closeBtn.disabled = disabled;
}

function updateStoreStatusBadge(status) {
    const badge = document.getElementById("store-status-badge");
    if (!badge) return;

    badge.classList.remove("open", "closed");

    if (status === "open") {
        badge.classList.add("open");
        badge.textContent = "OPEN";
    } else {
        badge.classList.add("closed");
        badge.textContent = "CLOSED";
    }
}

function updateSelectedLocationName(name) {
    const nameElement = document.getElementById("selected-location-name");
    if (nameElement && name) nameElement.textContent = name;
}

function updateStoreOverrideDetails(data) {
    const details = document.getElementById("store-override-details");
    const until = document.getElementById("store-override-until");
    const reason = document.getElementById("store-override-reason");

    if (!details) return;

    const active = Boolean(data.override_active);
    details.hidden = !active;

    if (until) {
        until.textContent = active && data.override_until_display
            ? `until ${data.override_until_display}`
            : "";
    }

    if (reason) {
        reason.textContent = active && data.override_reason
            ? data.override_reason
            : "";
    }
}

function loadStoreStatus(selectedLocation) {
    if (!selectedLocation) return;

    fetch(`api/store-status/${encodeURIComponent(selectedLocation)}/`, {
        method: "GET",
        headers: {
            "X-CSRFToken": getCookie("csrftoken")
        }
    })
    .then(response => {
        return response.json().then(data => ({
            ok: response.ok,
            data: data
        }));
    })
    .then(({ ok, data }) => {
        if (!ok) throw new Error(data.error || "Failed to load store status.");

        updateSelectedLocationName(data.location_name);
        updateStoreStatusBadge(data.status);
        updateStoreOverrideDetails(data);
    })
    .catch(error => {
        console.error("Error loading store status:", error);
        showStoreStatusMessage(error.message || "Error loading store status.", true);
    });
}

function setStoreStatus(status, selectedLocation) {
    if (!selectedLocation) {
        showStoreStatusMessage("Please select a location first.", true);
        return;
    }

    const url = "api/bland/set-store-status/";

    setButtonsDisabled(true);
    showStoreStatusMessage("Updating store status...");

    const reasonInput = document.getElementById("manual-override-reason");
    const reason = reasonInput ? reasonInput.value.trim() : "";

    fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken")
        },
        body: JSON.stringify({
            status: status,
            location_slug: selectedLocation,
            reason: reason,
        })
    })
    .then(response => {
        return response.json().then(data => ({
            ok: response.ok,
            data: data
        }));
    })
    .then(({ ok, data }) => {
        if (!ok) {
            throw new Error(data.error || "Failed to update store status.");
        }

        showStoreStatusMessage(data.message || "Store status updated successfully.");
        updateSelectedLocationName(data.location_name);
        updateStoreStatusBadge(data.status || status);
        updateStoreOverrideDetails(data);
        if (reasonInput) reasonInput.value = "";
        console.log("Store Status Updated:", data);
    })
    .catch((error) => {
        console.error("Error updating store status:", error);
        showStoreStatusMessage(error.message || "Error updating store status.", true);
    })
    .finally(() => {
        setButtonsDisabled(false);
    });
}

function updateWorkerRowUI(button, isActive) {

    const row = button.closest("tr");

    const badge = row.querySelector(".staff-status-badge");

    badge.classList.remove("active", "inactive");

    if (isActive) {

        badge.classList.add("active");
        badge.textContent = "Active";

        button.textContent = "Deactivate";

    } else {

        badge.classList.add("inactive");
        badge.textContent = "Inactive";

        button.textContent = "Activate";

    }

}

document.addEventListener("DOMContentLoaded", function () {
    const openBtn = document.getElementById("open-btn");
    const closeBtn = document.getElementById("close-btn");
    const locationSelect = document.getElementById("location-select");

    const buttons = document.querySelectorAll('.toggle-worker-btn');

    buttons.forEach(button => {
        button.addEventListener('click', function () {
            const workerId = this.dataset.workerId;
            const clickedButton = this;
    
            fetch('toggle-worker-status/', {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken")
                },
                body: JSON.stringify({
                    worker_id: workerId
                })
            })
            .then(response => {
                return response.json().then(data => ({
                    ok: response.ok,
                    data: data
                }));
            })
            .then(({ ok, data }) => {
                if (!ok) {
                    throw new Error(data.error || "Failed to update worker status.");
                }
    
                updateWorkerRowUI(clickedButton, data.is_active);
            })
            .catch(err => {
                alert(err.message);
            });
        });
    });

    if (openBtn) {
        openBtn.addEventListener("click", function () {
            const selectedLocation = getSelectedLocationSlug();
            setStoreStatus("open", selectedLocation);
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener("click", function () {
            const selectedLocation = getSelectedLocationSlug();
            setStoreStatus("closed", selectedLocation);
        });
    }

    if (locationSelect) {
        locationSelect.addEventListener("change", function () {
            const selectedLocation = this.value;
            const reasonInput = document.getElementById("manual-override-reason");
            if (reasonInput) reasonInput.value = "";

            if (!selectedLocation) {
                updateSelectedLocationName("Selected restaurant");
                updateStoreStatusBadge("closed");
                updateStoreOverrideDetails({ override_active: false });
                return;
            }

            loadStoreStatus(selectedLocation);
        });
    }

    const initialLocation = getSelectedLocationSlug();
    if (initialLocation) loadStoreStatus(initialLocation);
});
