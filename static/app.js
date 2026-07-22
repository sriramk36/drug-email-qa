document.addEventListener("DOMContentLoaded", () => {
    // UI Elements
    const form = document.getElementById("configForm");
    const channelSelect = document.getElementById("channel");
    const emailTypeLabel = document.getElementById("emailTypeLabel");
    const logConsole = document.getElementById("logConsole");
    const generateBtn = document.getElementById("generateBtn");
    const resultsCard = document.getElementById("resultsCard");
    const previewFrame = document.getElementById("previewFrame");
    const auditTable = document.getElementById("auditTable").querySelector("tbody");
    const rawCodeBlock = document.getElementById("rawCodeBlock");
    const historyTable = document.getElementById("historyTable").querySelector("tbody");

    // Toggle email type based on channel
    channelSelect.addEventListener("change", (e) => {
        if(e.target.value === "email") {
            emailTypeLabel.style.display = "block";
        } else {
            emailTypeLabel.style.display = "none";
        }
    });

    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            
            btn.classList.add("active");
            document.getElementById(btn.dataset.tab).classList.add("active");
        });
    });

    function logMessage(msg, type="info") {
        const div = document.createElement("div");
        div.className = `log-entry ${type}`;
        const time = new Date().toLocaleTimeString();
        div.textContent = `[${time}] ${msg}`;
        logConsole.appendChild(div);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    // Fetch history
    async function fetchHistory() {
        try {
            const res = await fetch("/api/history");
            const data = await res.json();
            historyTable.innerHTML = "";
            data.forEach(row => {
                const tr = document.createElement("tr");
                const badgeClass = row.all_passed ? "pass" : "fail";
                tr.innerHTML = `
                    <td>${row.id}</td>
                    <td>${row.market}</td>
                    <td>${row.audience}</td>
                    <td><span class="badge ${badgeClass}">${row.passed} ✓ | ${row.failed} ✗</span></td>
                    <td>${new Date(row.created_at).toLocaleString()}</td>
                `;
                historyTable.appendChild(tr);
            });
        } catch (e) {
            console.error("Failed to fetch history");
        }
    }
    fetchHistory();

    // Generate submission
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        generateBtn.disabled = true;
        logConsole.innerHTML = "";
        resultsCard.style.display = "none";
        logMessage("Starting generation pipeline...");

        const payload = {
            channel: form.channel.value,
            email_type: form.channel.value === "email" ? form.email_type.value : null,
            market: form.market.value,
            audience: form.audience.value,
            brand: form.brand.value,
            objective: form.objective.value,
            classification: form.classification.value,
            run_soft_review: form.run_soft_review.checked,
            images: {}
        };

        try {
            const response = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.body) throw new Error("ReadableStream not supported");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split("\n");
                
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const dataStr = line.replace("data: ", "").trim();
                        if (!dataStr) continue;
                        
                        try {
                            const data = JSON.parse(dataStr);
                            
                            if (data.error) {
                                logMessage(`Error: ${data.error}`, "error");
                                break;
                            }
                            
                            if (data.done) {
                                logMessage("Pipeline completed successfully!", "success");
                                
                                // Render Results
                                resultsCard.style.display = "block";
                                previewFrame.srcdoc = data.html;
                                rawCodeBlock.textContent = data.html;
                                
                                auditTable.innerHTML = "";
                                if (data.report && data.report.items) {
                                    data.report.items.forEach(item => {
                                        const tr = document.createElement("tr");
                                        const status = item.passed ? '<span class="badge pass">Pass</span>' : 
                                                       (item.severity === 'warning' ? '<span class="badge warn">Warn</span>' : '<span class="badge fail">Fail</span>');
                                        tr.innerHTML = `
                                            <td><strong>${item.rule_id}</strong><br><small>${item.label}</small></td>
                                            <td>${status}</td>
                                            <td>${item.detail}</td>
                                        `;
                                        auditTable.appendChild(tr);
                                    });
                                }
                                fetchHistory();
                            } else if (data.node) {
                                let msg = `Node completed: ${data.node}`;
                                if (data.node === "grade" && data.update.grade_report) {
                                    const report = data.update.grade_report;
                                    const fails = report.items.filter(i => !i.passed && i.severity === 'blocking').length;
                                    if (report.all_passed) {
                                        msg += ` - All blocking checks passed.`;
                                        logMessage(msg, "success");
                                        continue;
                                    } else {
                                        msg += ` - Failed ${fails} blocking rules. Rewriting...`;
                                        logMessage(msg, "error");
                                        continue;
                                    }
                                }
                                logMessage(msg);
                            }
                        } catch (err) {
                            console.error("JSON parse error on chunk", err, dataStr);
                        }
                    }
                }
            }
        } catch (err) {
            logMessage(`Request failed: ${err.message}`, "error");
        } finally {
            generateBtn.disabled = false;
        }
    });
});
