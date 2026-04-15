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


function setStoreStatus(status, selectedLocation) {
    if (!selectedLocation) {
        showStoreStatusMessage("Please select a location first.", true);
        return;
    }

    const url = "test/api/bland/set-store-status/";

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

document.addEventListener("DOMContentLoaded", function () {
    const openBtn = document.getElementById("open-btn");
    const closeBtn = document.getElementById("close-btn");

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