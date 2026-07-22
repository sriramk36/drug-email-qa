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

    const nodeIcons = {
        "resolve": "🔍",
        "generate": "✨",
        "grade": "🛡️",
        "soft_review": "💬",
        "info": "ℹ️",
        "success": "✅",
        "error": "❌"
    };

    function logMessage(msgHtml, type="info") {
        const div = document.createElement("div");
        div.className = `log-entry status-${type}`;
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
        const icon = nodeIcons[type] || nodeIcons["info"];
        
        div.innerHTML = `
            <div class="step-icon">${icon}</div>
            <div class="step-content">
                <div class="step-msg">${msgHtml}</div>
                <div class="step-time">${time}</div>
            </div>
        `;
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
                const compBadgeClass = row.all_passed ? "pass" : "fail";
                const complianceStr = `${row.passed || 0}/${(row.passed || 0) + (row.failed || 0) + (row.warned || 0)}`;
                
                const status = row.all_passed ? "Draft" : "Blocked";
                const statusColor = row.all_passed ? "var(--success)" : "var(--danger)";
                
                tr.innerHTML = `
                    <td>${row.id}</td>
                    <td style="text-transform: capitalize;">${row.channel}</td>
                    <td>${row.type || "-"}</td>
                    <td>${row.market}</td>
                    <td>${row.audience}</td>
                    <td style="max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${row.objective}">${row.objective}</td>
                    <td><span class="badge ${compBadgeClass}">${complianceStr}</span></td>
                    <td style="color: ${statusColor}; font-weight: 600;">${status}</td>
                    <td>${row.iterations || 1}</td>
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
        generateBtn.innerHTML = '<div class="spinner" style="display:block;"></div> Processing...';
        logConsole.innerHTML = "";
        resultsCard.style.display = "none";
        logMessage("Starting generation pipeline...");

        // 1. Process Images to Base64
        const fileInput = document.getElementById("images");
        const imagesDict = {};
        if (fileInput && fileInput.files.length > 0) {
            for (let i = 0; i < fileInput.files.length; i++) {
                const file = fileInput.files[i];
                const reader = new FileReader();
                await new Promise((resolve) => {
                    reader.onload = (e) => {
                        imagesDict[file.name] = e.target.result;
                        resolve();
                    };
                    reader.readAsDataURL(file);
                });
            }
        }

        const payload = {
            channel: document.getElementById("channel").value,
            email_type: document.getElementById("email_type") ? document.getElementById("email_type").value : null,
            market: document.getElementById("market").value,
            audience: document.getElementById("audience").value,
            brand: document.getElementById("brand").value,
            classification: document.getElementById("classification").value,
            objective: document.getElementById("objective").value,
            run_soft_review: document.getElementById("run_soft_review").checked,
            images: imagesDict
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
                                previewFrame.srcdoc = data.html_preview || data.html;
                                rawCodeBlock.textContent = data.html;
                                
                                // Configure Download Button
                                const downloadBtn = document.getElementById("downloadBtn");
                                const blob = new Blob([data.html], { type: "text/html" });
                                const url = URL.createObjectURL(blob);
                                downloadBtn.href = url;
                                downloadBtn.download = data.meta ? `${data.meta.id}.html` : "draft.html";
                                downloadBtn.style.display = "inline-block";
                                
                                // Configure Copy Button
                                const copyBtn = document.getElementById("copyBtn");
                                copyBtn.style.display = "inline-block";
                                copyBtn.onclick = () => {
                                    navigator.clipboard.writeText(data.html);
                                    copyBtn.innerHTML = "✅ Copied!";
                                    setTimeout(() => copyBtn.innerHTML = "📋 Copy HTML", 2000);
                                };
                                
                                // Render Top-Level Metrics
                                if (data.meta) {
                                    const mb = document.getElementById("metricsBar");
                                    mb.innerHTML = `
                                        <div class="metric-box">
                                            <div class="metric-label">Passed</div>
                                            <div class="metric-value pass">${data.meta.passed || 0}</div>
                                        </div>
                                        <div class="metric-box">
                                            <div class="metric-label">Failed</div>
                                            <div class="metric-value fail">${data.meta.failed || 0}</div>
                                        </div>
                                        <div class="metric-box">
                                            <div class="metric-label">Warnings</div>
                                            <div class="metric-value warn">${data.meta.warned || 0}</div>
                                        </div>
                                        <div class="metric-box">
                                            <div class="metric-label">Iterations</div>
                                            <div class="metric-value" style="color:var(--primary-color)">${data.meta.iterations || 0}</div>
                                        </div>
                                        <div class="metric-box">
                                            <div class="metric-label">Total Time</div>
                                            <div class="metric-value" style="color:var(--text-muted)">${data.meta.elapsed || "0.0"}s</div>
                                        </div>
                                    `;
                                }
                                
                                // Render Grouped Audit Sections + Progress Bar
                                const auditGroups = document.getElementById("auditGroups");
                                const auditEmpty = document.getElementById("auditEmpty");
                                const auditBody = document.getElementById("auditBody");
                                const complianceProgress = document.getElementById("complianceProgress");
                                const softReviewSection = document.getElementById("softReviewSection");

                                auditGroups.innerHTML = "";
                                softReviewSection.innerHTML = "";
                                auditEmpty.style.display = "none";
                                auditBody.style.display = "block";

                                if (data.report && data.report.items) {
                                    const items = data.report.items;
                                    const total = items.length;
                                    const passedCount = items.filter(i => i.passed).length;
                                    const pct = total > 0 ? Math.round((passedCount / total) * 100) : 0;
                                    const barColor = pct === 100 ? "var(--success)" : pct >= 70 ? "var(--warning)" : "var(--danger)";

                                    complianceProgress.innerHTML = `
                                        <div class="compliance-bar-wrap">
                                            <div class="compliance-bar-label">${passedCount} / ${total} Checks Passed (${pct}%)</div>
                                            <div class="compliance-bar"><div class="compliance-bar-fill" style="width:${pct}%; background:${barColor};"></div></div>
                                        </div>
                                    `;

                                    const renderGroup = (title, icon, items, headerClass, expanded) => {
                                        if (items.length === 0) return;
                                        const groupEl = document.createElement("div");
                                        groupEl.className = "audit-group";
                                        const bodyId = `ag-${Math.random().toString(36).slice(2)}`;
                                        groupEl.innerHTML = `
                                            <div class="audit-group-header ${headerClass}" onclick="const b=document.getElementById('${bodyId}'); b.style.display=b.style.display==='none'?'block':'none'; this.querySelector('.chevron').textContent=b.style.display==='none'?'▶':'▼';">
                                                <span>${icon} ${title} (${items.length})</span>
                                                <span class="chevron">${expanded ? '▼' : '▶'}</span>
                                            </div>
                                            <div class="audit-group-body" id="${bodyId}" style="display:${expanded ? 'block' : 'none'};">
                                                ${items.map(item => {
                                                    const icon = item.passed ? "✅" : (item.severity === "warning" ? "⚠️" : "❌");
                                                    return `<div class="audit-item">
                                                        <div class="audit-item-icon">${icon}</div>
                                                        <div>
                                                            <div class="audit-item-label">${item.label} <small style="font-weight:400; color:var(--text-muted);">(${item.rule_id})</small></div>
                                                            <div class="audit-item-detail">${item.detail}</div>
                                                        </div>
                                                    </div>`;
                                                }).join("")}
                                            </div>
                                        `;
                                        auditGroups.appendChild(groupEl);
                                    };

                                    const blocking = items.filter(i => !i.passed && i.severity === "blocking");
                                    const warnings = items.filter(i => !i.passed && i.severity === "warning");
                                    const passed   = items.filter(i => i.passed);

                                    renderGroup("Blocking Failures", "❌", blocking, "blocking", true);
                                    renderGroup("Warnings", "⚠️", warnings, "warning", true);
                                    renderGroup("Passed Checks", "✅", passed, "passed", false);
                                }

                                // Render Soft Review Advisory Notes
                                const notes = data.soft_review_notes || [];
                                if (notes.length > 0) {
                                    let html = `<div class="advisory-section-title">💬 Soft Review Advisory <small style="font-weight:400; color:var(--text-muted);">(AI — advisory only, not verified findings)</small></div>`;
                                    notes.forEach(n => {
                                        html += `<div class="advisory-note">
                                            <div class="advisory-note-title">${n.concern || "Advisory"}</div>
                                            <div class="advisory-note-detail">${n.detail || ""}</div>
                                        </div>`;
                                    });
                                    softReviewSection.innerHTML = html;
                                }
                                
                                // Render Iteration History
                                const iterTable = document.querySelector("#iterHistoryTable tbody");
                                iterTable.innerHTML = "";
                                if (data.iteration_history) {
                                    data.iteration_history.forEach(iter => {
                                        const tr = document.createElement("tr");
                                        let changes = "";
                                        if (iter.rectified && iter.rectified.length > 0) changes += `<div style="color:var(--success)">Rectified: ${iter.rectified.join(", ")}</div>`;
                                        if (iter.new_failures && iter.new_failures.length > 0) changes += `<div style="color:var(--danger)">New: ${iter.new_failures.join(", ")}</div>`;
                                        if (!changes && iter.attempt > 1) changes = `<div style="color:var(--text-muted)">No rule changes</div>`;
                                        
                                        tr.innerHTML = `
                                            <td>Attempt ${iter.attempt}</td>
                                            <td>${iter.passed}</td>
                                            <td>${iter.failed}</td>
                                            <td>${iter.warned}</td>
                                            <td>${changes || "-"}</td>
                                        `;
                                        iterTable.appendChild(tr);
                                    });
                                }
                                
                                fetchHistory();
                            } else if (data.node) {
                                let nodeName = data.node;
                                if (nodeName === "resolve") {
                                    let mi = data.update.market_info;
                                    let ai = data.update.audience_info;
                                    if (mi && ai) {
                                        logMessage(`Market → <strong>${mi.market_text}</strong> (${mi.source})<br>Audience → <strong>${ai.audience_text}</strong> (${ai.source})`, "resolve");
                                    }
                                } else if (nodeName === "generate") {
                                    let iter = data.update.iteration || 1;
                                    logMessage(iter === 1 ? `First draft generated (attempt 1). Verifying...` : `Revised draft generated (attempt ${iter}). Re-verifying...`, "generate");
                                } else if (nodeName === "soft_review") {
                                    let notes = data.update.soft_review_notes || [];
                                    logMessage(notes.length > 0 ? `Flagged <strong>${notes.length}</strong> advisory notes.` : `No concerns flagged ✓`, "soft_review");
                                } else if (nodeName === "grade" && data.update.grade_report) {
                                    const report = data.update.grade_report;
                                    const fails = report.items.filter(i => !i.passed && i.severity === 'blocking');
                                    const warns = report.items.filter(i => !i.passed && i.severity === 'warning');
                                    
                                    if (fails.length === 0) {
                                        if (warns.length > 0) {
                                            logMessage(`Passed all blocking checks (with <strong>${warns.length}</strong> warning(s)).`, "grade");
                                        } else {
                                            logMessage(`Passed all compliance checks.`, "success");
                                        }
                                    } else {
                                        let html = `Failed <strong>${fails.length}</strong> blocking rule(s).`;
                                        
                                        if (data.delta && Object.keys(data.delta).length > 0) {
                                            html += `<div class="delta-box">`;
                                            if (data.delta.rectified && data.delta.rectified.length > 0) {
                                                html += `<div><strong style="color:var(--success)">Rectified from prior attempt:</strong> ${data.delta.rectified.join(", ")}</div>`;
                                            }
                                            if (data.delta.still_failing && data.delta.still_failing.length > 0) {
                                                html += `<div><strong style="color:var(--danger)">Still failing:</strong> ${data.delta.still_failing.join(", ")}</div>`;
                                            }
                                            if (data.delta.new_failures && data.delta.new_failures.length > 0) {
                                                html += `<div><strong style="color:var(--danger)">New failures this iteration:</strong> ${data.delta.new_failures.join(", ")}</div>`;
                                            }
                                            html += `</div>`;
                                        }
                                        
                                        // log detailed reasons
                                        html += `<div class="fail-box">`;
                                        fails.forEach(f => {
                                            html += `<div style="margin-bottom:0.25rem;"><strong>${f.rule_id}</strong>: ${f.detail}</div>`;
                                        });
                                        html += `</div>`;
                                        
                                        logMessage(html, "grade");
                                    }
                                } else {
                                    logMessage(`Node completed: ${nodeName}`, "info");
                                }
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
            generateBtn.innerHTML = "Run Generation";
        }
    });
});
