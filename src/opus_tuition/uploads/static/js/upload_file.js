// Perform multi-file upload process and updates the history table dynamically based on database.
document.getElementById("uploadForm").onsubmit = async (e) => {
    e.preventDefault();
    document.getElementById("loader").classList.remove("hidden");
    
    const fileInput = document.getElementById("fileInput");
    const formData = new FormData();

    // Loop through all selected files and append each one
    for (let i = 0; i < fileInput.files.length; i++) {
        formData.append("file", fileInput.files[i]);
    }
    
    // Perform the file upload via API request
    try {
        const response = await fetch("/api/upload/", { 
            method: "POST",
            headers: { "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value },
            body: formData 
        });
        
        // Inside your onsubmit handler:
        const result = await response.json();

        // Handle response and refresh the view if successful
        if (response.ok) {
            result.results.forEach(res => {
                if (res.success) {
                    // Add to table
                    const rep = res.report;
                    const statusClass = (rep.upload_status === "COMPLETED") ? "success" : "danger";
                    
                    document.getElementById("historyBody").insertAdjacentHTML("afterbegin", `
                        <tr>
                            <td>${rep.upload_id}</td>
                            <td>${rep.file_name}</td>
                            <td><span class="badge ${statusClass}">${rep.upload_status}</span></td>
                            <td>
                                <button onclick="loadUploadContext('${rep.upload_id}', '${rep.file_name}')">
                                    Examine Details
                                </button>
                            </td>
                        </tr>
                    `);
                } else {
                    alert(`Error processing ${res.file}: ${res.error}`);
                }
            });
        }
        
    } catch (err) {
        alert("Upload failed. Check console for details.");
        console.error(err);
    } finally {
        document.getElementById("loader").classList.add("hidden");
    }
};

//  Maps JSON data objects into HTML table rows for clean records dataset
function renderCleanTable(data) {
    const tbody = document.querySelector("#cleanRecordsTable tbody");
    tbody.innerHTML = data.map(r => `
        <tr>
            <td>
                <div>
                    <button class="btn-delete" onclick="deleteRecord('cleaned', '${r.clean_record_id}')" title="Delete">
                    &times;</button>
                    <span>${r.clean_record_id}</span>
                </div>
            </td>
            <td><pre>${JSON.stringify(r.data, null, 2)}</pre></td>
        </tr>`).join("");
}

//  Maps JSON data objects into HTML table rows for quarantine records dataset
function renderQuarantineTable(data) {
    const tbody = document.querySelector("#quarantineTable tbody");
    
    tbody.innerHTML = data.map(r => `
        <tr>
            <td>
                <button class="btn-delete" onclick="deleteRecord('quarantine', '${r.quarantine_record_id}')">&times;</button>
                <span>${r.quarantine_record_id}</span>
            </td>
            <td>
                <span class="badge danger">${r.reason_code}</span>
                <div style="font-size: 0.85em; color: #555; margin-top: 4px;">
                    ${r.error_details || "No details provided"}
                </div>
            </td>
            <td><textarea id="json-edit-${r.quarantine_record_id}">${JSON.stringify(r.raw_data)}</textarea></td>
            <td>
                <button onclick="resubmitRow('${r.quarantine_record_id}')" style="margin-bottom: 5px;">Resubmit</button>
            </td>
        </tr>`).join('')
}

// Fetches the full report based on specific Upload ID and refreshes the Dashboard workspace.
async function loadUploadContext(id, file_name) {
    document.getElementById("workspaceContainer").classList.remove("hidden");
    document.getElementById("activeTargetName").innerText = `#${id} - ${file_name}`;
    
    const downloadCleanReportBtn = document.getElementById("downloadCleanReportBtn");
    downloadCleanReportBtn.href = `/download-cleaned-records/${id}/`;
    
    const downloadFullReportBtn = document.getElementById("downloadFullReportBtn");
    downloadFullReportBtn.href = `/download-full-report/${id}/`;

    const response = await fetch(`/api/report/${id}/`);

    if (!response.ok) {
        console.error("Server responded with error:", response.status);
        return;
    }
    
    const result = await response.json();

    const rep = result.report;

    // Update Summary Stats
    if (rep.metrics) {
        document.getElementById("stat-total").innerText = rep.metrics.total_rows_received;
        document.getElementById("stat-accepted").innerText = rep.metrics.rows_accepted;
        document.getElementById("stat-quarantined").innerText = rep.metrics.rows_quarantined;
    }
    
    // 4. Render the data
    renderCleanTable(result.report.clean_records || []);
    renderQuarantineTable(result.report.quarantine_records || []);
}

// Updates a record from the database based on their record id.
async function resubmitRow(row_id) {
    const textarea = document.getElementById(`json-edit-${row_id}`);
    const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
    
    let correctedPayload;
    try {
        correctedPayload = JSON.parse(textarea.value);
    } catch (e) {
        alert("Invalid JSON format in the textarea. Please fix it and try again.");
        return;
    }

    // Perform the resubmission via API request
    const response = await fetch(`/api/quarantine/${row_id}/`, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken
        },
        body: JSON.stringify({ corrected_payload: correctedPayload })
    });

    const result = await response.json();

    // Handle response and refresh the view if successful
    if (response.ok) {
        const currentUploadId = document.getElementById("activeTargetName").innerText.split(" ")[0].replace("#", "");
        loadUploadContext(currentUploadId, "Current File"); 
    } else {
        // The result object now contains an 'errors' array
        if (result.errors && Array.isArray(result.errors)) {
            // Map over the array to get all error messages
            const errorMessage = result.errors.map(err => err.message).join("\n");
            alert(`Validation Failed:\n${errorMessage}`);
        } else if (result.error) {
            // Fallback for single error responses
            alert(`Error: ${typeof result.error === 'object' ? JSON.stringify(result.error) : result.error}`);
        } else {
            alert("An unexpected error occurred.");
        }
    }
}

// Permanently removes a record from the database based on their record category and record id
async function deleteRecord(record_type, record_id) {
    // Presents a modal dialog with "OK" and "Cancel" buttons
    if (!confirm("Permanently delete this row?")) return;

    // Perform the deletion via API request
    const response = await fetch(`/api/delete/${record_type}/${record_id}/`, {
        method: "DELETE",
        headers: { "X-CSRFToken": document.querySelector("[name=csrfmiddlewaretoken]").value }
    });

    const result = await response.json();

    // Handle response and refresh the view if successful
    if (response.ok) {
        alert("Success: Row deleted!");
        // Extract current upload context to refresh the display accurately
        const currentUploadId = document.getElementById("activeTargetName").innerText.split(" ")[0].replace("#", "");
        loadUploadContext(currentUploadId, "Current File"); 
    } else {
        // Provide detailed error feedback if the deletion fails
        alert(`Failed: ${JSON.stringify(result.error.details || {})}`);
    }
}

function closeWorkspace() { document.getElementById("workspaceContainer").classList.add("hidden"); }
