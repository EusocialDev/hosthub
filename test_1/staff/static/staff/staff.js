function setStoreStatus(status, selectedLocation) {
    const url = `api/bland/set-store-status/`;
    fetch (url,{
        method: `POST`,
        headers: {
            'Content-Type': 'application/json',
            "X-CSRFToken": getCookie("csrftoken")
        },
        body: JSON.stringify({
            status: status,
            location: selectedLocation,
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log("Store Status Updated:", data);
    })
    .catch((error) => { 
        console.error("Error updating store status:", error);
    });

}