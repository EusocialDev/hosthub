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

function setStoreStatus(status, selectedLocation) {
    if (!selectedLocation) {
        showStoreStatusMessage("Please select a location first.", true);
        return;
    }

    const url = "api/bland/set-store-status/";

    setButtonsDisabled(true);
    showStoreStatusMessage("Updating store status...");

    fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCookie("csrftoken")
        },
        body: JSON.stringify({
            status: status,
            location_slug: selectedLocation,
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
        updateStoreStatusBadge(status);
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
});