const loginScreen = document.querySelector("#login-screen");
const appScreen = document.querySelector("#app-screen");
const notice = document.querySelector("#notice");
const titles = {
  overview: "Overview",
  feed: "Camera feed",
  account: "My account",
  logs: "Access logs",
  students: "Students",
  enroll: "Biometric enrollment",
  cameras: "RTSP cameras",
  users: "User accounts",
  activity: "Activity history",
};

let currentUser;
let noticeTimer;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    if (response.status === 401) showLogin();
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return body;
}

function showNotice(message, isError = false) {
  clearTimeout(noticeTimer);
  notice.textContent = message;
  notice.classList.toggle("error-notice", isError);
  notice.hidden = false;
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 5000);
}

function showLogin() {
  currentUser = null;
  loginScreen.hidden = false;
  appScreen.hidden = true;
  const image = document.querySelector("#camera-feed");
  image.hidden = true;
  image.removeAttribute("src");
}

function setView(name) {
  const permitted = [...document.querySelectorAll(`[data-view="${name}"]`)]
    .some((item) => item.hidden !== true);
  if (!permitted) return;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === name);
  });
  document.querySelector("#page-title").textContent = titles[name] || "Overview";
  if (name === "feed") refreshCameras().then(connectFeed);
  if (name === "logs") refreshLogs();
  if (name === "students") refreshStudents();
  if (name === "cameras") refreshCameras();
  if (name === "users") refreshUsers();
  if (name === "activity") refreshActivity();
}

function applyRoleAccess() {
  const role = currentUser.role;
  document.querySelectorAll("[data-roles]").forEach((element) => {
    const roles = element.dataset.roles.split(",");
    element.hidden = !roles.includes(role);
  });
  document.querySelector("#account-name").textContent = currentUser.username;
  document.querySelector("#account-role").textContent = role.replaceAll("_", " ");
  document.querySelector("#welcome-name").textContent = currentUser.username;
  const roleSelect = document.querySelector("#new-user-role");
  const assignableRoles = role === "SUPER_ADMIN"
    ? ["ADMIN", "SECURITY_OFFICER", "GATE_PERSONNEL", "GATE_DEVICE", "SUPER_ADMIN"]
    : ["GATE_PERSONNEL", "GATE_DEVICE"];
  roleSelect.innerHTML = assignableRoles
    .map((value) => `<option value="${value}">${value.replaceAll("_", " ")}</option>`)
    .join("");
  loginScreen.hidden = true;
  appScreen.hidden = false;
  setView("overview");
}

async function refreshCameras() {
  const select = document.querySelector("#camera-select");
  try {
    const cameras = await api("/api/admin/cameras");
    const selected = select.value || "webcam";
    select.innerHTML = cameras
      .map((camera) => `<option value="${escapeHtml(camera.camera_id)}">${escapeHtml(camera.camera_name)} · ${escapeHtml(camera.status)}</option>`)
      .join("");
    if ([...select.options].some((option) => option.value === selected)) select.value = selected;
    document.querySelector("#cameras-body").innerHTML = cameras.length
      ? cameras.map((camera) => {
        const canManage = ["SUPER_ADMIN", "ADMIN"].includes(currentUser.role);
        const controls = canManage
          ? `${camera.status === "ONLINE"
            ? `<button class="secondary camera-action" data-action="stop" data-id="${escapeHtml(camera.camera_id)}">Stop</button>`
            : `<button class="camera-action" data-action="start" data-id="${escapeHtml(camera.camera_id)}">Start</button>`}
            ${camera.type === "rtsp" ? `<button class="secondary camera-action" data-action="edit" data-id="${escapeHtml(camera.camera_id)}">Edit</button><button class="danger camera-action" data-action="delete" data-id="${escapeHtml(camera.camera_id)}">Delete</button>` : ""}`
          : "";
        return `<tr><td>${escapeHtml(camera.camera_id)}</td><td>${escapeHtml(camera.camera_name)}</td><td><span class="state-badge ${camera.status === "ONLINE" ? "online" : "offline"}">${escapeHtml(camera.status)}</span></td><td>${camera.is_selected ? "Yes" : "No"}</td><td data-roles="SUPER_ADMIN,ADMIN">${controls}</td></tr>`;
      }).join("")
      : '<tr><td colspan="5" class="muted">No cameras available.</td></tr>';
    applyRoleVisibility();
    return cameras;
  } catch (error) {
    showNotice(error.message, true);
    return [];
  }
}

async function refreshLogs() {
  try {
    const logs = await api("/api/admin/logs?limit=100");
    document.querySelector("#logs-body").innerHTML = logs.length
      ? logs.map((log) => `<tr><td>${escapeHtml(log.timestamp)}</td><td>${escapeHtml(log.student_id || "—")}</td><td><span class="result">${escapeHtml(log.status_result)}</span></td><td>${log.confidence_distance == null ? "—" : Number(log.confidence_distance).toFixed(3)}</td><td data-roles="SUPER_ADMIN,ADMIN">${currentUser.role === "SUPER_ADMIN" || currentUser.role === "ADMIN" ? `<button class="secondary delete-log" data-id="${Number(log.log_id)}">Delete</button>` : "—"}</td></tr>`).join("")
      : '<tr><td colspan="5" class="muted">No access events recorded yet.</td></tr>';
    applyRoleVisibility();
  } catch (error) { showNotice(error.message, true); }
}

function applyRoleVisibility() {
  if (!currentUser) return;
  document.querySelectorAll("[data-roles]").forEach((element) => {
    element.hidden = !element.dataset.roles.split(",").includes(currentUser.role);
  });
}

async function refreshStudents() {
  try {
    const students = await api("/api/admin/students");
    document.querySelector("#students-body").innerHTML = students.length
      ? students.map((student) => `<tr class="clickable-row" tabindex="0" role="button" aria-label="View ${escapeHtml(student.full_name)}" data-student-id="${escapeHtml(student.student_id)}"><td>${escapeHtml(student.student_id)}</td><td>${escapeHtml(student.full_name)}</td><td>${escapeHtml(student.course)}</td><td>${escapeHtml(student.status)}</td></tr>`).join("")
      : '<tr><td colspan="4" class="muted">No students registered yet.</td></tr>';
  } catch (error) { showNotice(error.message, true); }
}

async function showStudentDetails(studentId) {
  try {
    const student = await api(`/api/admin/students/${encodeURIComponent(studentId)}`);
    const history = student.access_logs.length
      ? student.access_logs.map((log) => `<tr><td>${escapeHtml(log.timestamp || "—")}</td><td>${escapeHtml(log.status_result)}</td><td>${log.confidence_distance == null ? "—" : Number(log.confidence_distance).toFixed(3)}</td></tr>`).join("")
      : '<tr><td colspan="3" class="muted">No access history for this student.</td></tr>';
    document.querySelector("#student-detail-content").innerHTML = `
      <p class="eyebrow">STUDENT RECORD</p>
      <h2>${escapeHtml(student.full_name)}</h2>
      <div class="student-summary">
        <p><strong>Student ID</strong><span>${escapeHtml(student.student_id)}</span></p>
        <p><strong>Course</strong><span>${escapeHtml(student.course)}</span></p>
        <p><strong>Status</strong><span>${escapeHtml(student.status)}</span></p>
        <p><strong>Created</strong><span>${escapeHtml(student.created_at || "—")}</span></p>
        <p><strong>Biometric records</strong><span>${Number(student.biometric_enrollment_count)}</span></p>
      </div>
      <form id="student-edit-form" class="form-grid">
        <label>Full name<input name="full_name" value="${escapeHtml(student.full_name)}" maxlength="100" required></label>
        <label>Course<input name="course" value="${escapeHtml(student.course)}" maxlength="100" required></label>
        <label>Status<select name="status"><option ${student.status === "ACTIVE" ? "selected" : ""}>ACTIVE</option><option ${student.status === "SUSPENDED" ? "selected" : ""}>SUSPENDED</option><option ${student.status === "INACTIVE" ? "selected" : ""}>INACTIVE</option></select></label>
        <button type="submit">Save changes</button>
        <button type="button" id="delete-student-button" class="danger">Delete student permanently</button>
      </form>
      <h3>Recent access history</h3>
      <div class="table-wrap"><table><thead><tr><th>Time</th><th>Result</th><th>Match distance</th></tr></thead><tbody>${history}</tbody></table></div>`;
    const dialog = document.querySelector("#student-dialog");
    dialog.dataset.studentId = student.student_id;
    dialog.showModal();
  } catch (error) { showNotice(error.message, true); }
}

async function refreshActivity() {
  try {
    const activities = await api("/api/admin/activity?limit=500");
    document.querySelector("#activity-body").innerHTML = activities.length
      ? activities.map((item) => {
        const details = Object.entries(item.details || {})
          .map(([key, value]) => `${key}: ${value}`)
          .join(" · ");
        return `<tr><td>${escapeHtml(item.timestamp)}</td><td>${escapeHtml(item.actor_username)}<small class="table-subtext">${escapeHtml(item.actor_role)}</small></td><td>${escapeHtml(item.action.replaceAll("_", " "))}</td><td>${escapeHtml(item.entity_type)}${item.entity_id ? ` · ${escapeHtml(item.entity_id)}` : ""}</td><td>${escapeHtml(details || "—")}</td></tr>`;
      }).join("")
      : '<tr><td colspan="5" class="muted">No system activity recorded yet.</td></tr>';
  } catch (error) { showNotice(error.message, true); }
}

async function refreshUsers() {
  try {
    const users = await api("/api/admin/users");
    document.querySelector("#users-body").innerHTML = users.length
      ? users.map((user) => {
        const canDelete = user.username !== currentUser.username &&
          (currentUser.role === "SUPER_ADMIN" ||
            (currentUser.role === "ADMIN" && ["GATE_PERSONNEL", "GATE_DEVICE"].includes(user.role)));
        return `<tr><td>${escapeHtml(user.username)}</td><td>${escapeHtml(user.role.replaceAll("_", " "))}</td><td>${user.is_active ? "Active" : "Disabled"}</td><td>${canDelete ? `<button class="secondary delete-user" data-username="${escapeHtml(user.username)}">Delete account</button>` : "—"}</td></tr>`;
      }).join("")
      : '<tr><td colspan="4" class="muted">No user accounts.</td></tr>';
  } catch (error) { showNotice(error.message, true); }
}

async function connectFeed() {
  const image = document.querySelector("#camera-feed");
  const placeholder = document.querySelector("#feed-placeholder");
  const cameraId = document.querySelector("#camera-select").value;
  image.hidden = true;
  placeholder.hidden = false;
  placeholder.textContent = "Connecting to camera…";
  image.onload = () => { image.hidden = false; placeholder.hidden = true; };
  image.onerror = () => {
    image.hidden = true;
    placeholder.hidden = false;
    placeholder.textContent = "The feed could not be opened. Check the camera connection and try again.";
  };
  try {
    await api(`/api/admin/cameras/${encodeURIComponent(cameraId)}/switch`, { method: "POST" });
    const cameras = await api("/api/admin/cameras");
    const selectedCamera = cameras.find((camera) => camera.camera_id === cameraId);
    if (!selectedCamera || selectedCamera.status !== "ONLINE") {
      throw new Error("This camera is stopped. Ask an admin to start it before viewing.");
    }
    image.src = `/api/gate/video-feed?camera_id=${encodeURIComponent(cameraId)}&t=${Date.now()}`;
  } catch (error) {
    placeholder.textContent = error.message;
    showNotice(error.message, true);
  }
}

document.querySelector("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const message = document.querySelector("#login-error");
  message.textContent = "";
  message.style.color = "";
  try {
    await api("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ username: form.get("username"), password: form.get("password") }),
    });
    currentUser = await api("/api/admin/me");
    applyRoleAccess();
  } catch (error) { message.textContent = error.message; }
});

document.querySelector("#logout-button").addEventListener("click", async () => {
  try { await api("/api/admin/logout", { method: "POST" }); } finally { showLogin(); }
});

document.querySelector("#navigation").addEventListener("click", (event) => {
  const button = event.target.closest("[data-view]");
  if (button) setView(button.dataset.view);
});
document.querySelectorAll("[data-open-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.openView));
});

document.querySelector("#feed-refresh").addEventListener("click", connectFeed);
document.querySelector("#camera-select").addEventListener("change", connectFeed);
document.querySelector("#logs-refresh").addEventListener("click", refreshLogs);
document.querySelector("#students-refresh").addEventListener("click", refreshStudents);
document.querySelector("#cameras-refresh").addEventListener("click", refreshCameras);
document.querySelector("#users-refresh").addEventListener("click", refreshUsers);
document.querySelector("#activity-refresh").addEventListener("click", refreshActivity);

document.querySelector("#cameras-body").addEventListener("click", async (event) => {
  const button = event.target.closest(".camera-action");
  if (!button) return;
  const cameraId = button.dataset.id;
  const action = button.dataset.action;
  try {
    if (action === "delete") {
      if (!confirm(`Permanently delete camera ${cameraId}?`)) return;
      await api(`/api/admin/cameras/${encodeURIComponent(cameraId)}`, { method: "DELETE" });
      showNotice("Camera deleted.");
    } else if (action === "start" || action === "stop") {
      await api(`/api/admin/cameras/${encodeURIComponent(cameraId)}/${action}`, { method: "POST" });
      showNotice(`Camera ${action === "start" ? "started" : "stopped"}.`);
    } else if (action === "edit") {
      const row = button.closest("tr");
      const currentName = row.children[1].textContent;
      const cameraName = prompt("Camera name:", currentName);
      if (cameraName === null) return;
      const rtspUrl = prompt("New RTSP URL (leave blank to keep the current URL):");
      if (rtspUrl === null) return;
      const payload = { camera_name: cameraName };
      if (rtspUrl.trim()) payload.rtsp_url = rtspUrl.trim();
      await api(`/api/admin/cameras/${encodeURIComponent(cameraId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showNotice("Camera updated. Start it again if its RTSP URL changed.");
    }
    await refreshCameras();
  } catch (error) {
    showNotice(error.message, true);
    refreshCameras();
  }
});

document.querySelector("#students-body").addEventListener("click", (event) => {
  const row = event.target.closest("[data-student-id]");
  if (row) showStudentDetails(row.dataset.studentId);
});
document.querySelector("#students-body").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("[data-student-id]");
  if (!row) return;
  event.preventDefault();
  showStudentDetails(row.dataset.studentId);
});

document.querySelector("#student-detail-content").addEventListener("submit", async (event) => {
  if (event.target.id !== "student-edit-form") return;
  event.preventDefault();
  const studentId = document.querySelector("#student-dialog").dataset.studentId;
  const values = Object.fromEntries(new FormData(event.target));
  try {
    await api(`/api/admin/students/${encodeURIComponent(studentId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(values),
    });
    showNotice("Student record updated.");
    await refreshStudents();
    showStudentDetails(studentId);
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#student-detail-content").addEventListener("click", async (event) => {
  if (event.target.id !== "delete-student-button") return;
  const dialog = document.querySelector("#student-dialog");
  const studentId = dialog.dataset.studentId;
  if (!confirm(`Permanently delete student ${studentId}, including their biometric records?`)) return;
  try {
    await api(`/api/admin/students/${encodeURIComponent(studentId)}`, { method: "DELETE" });
    dialog.close();
    showNotice("Student and biometric records deleted.");
    refreshStudents();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#logs-body").addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-log");
  if (!button || !confirm("Permanently delete this access log?")) return;
  try {
    await api(`/api/admin/logs/${button.dataset.id}`, { method: "DELETE" });
    showNotice("Access log deleted.");
    refreshLogs();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#logs-delete-all").addEventListener("click", async () => {
  if (!confirm("Permanently delete every access log? This cannot be undone.")) return;
  try {
    const result = await api("/api/admin/logs", { method: "DELETE" });
    showNotice(`${result.deleted_count} access log(s) deleted.`);
    refreshLogs();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#users-body").addEventListener("click", async (event) => {
  const button = event.target.closest(".delete-user");
  if (!button || !confirm(`Delete account "${button.dataset.username}"?`)) return;
  try {
    await api(`/api/admin/users/${encodeURIComponent(button.dataset.username)}`, { method: "DELETE" });
    showNotice("User account deleted.");
    refreshUsers();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#wipe-system-button").addEventListener("click", async () => {
  const confirmation = prompt('This permanently removes all data and all accounts, including yours. Type WIPE EVERYTHING to continue:');
  if (confirmation !== "WIPE EVERYTHING") return;
  try {
    await api(`/api/admin/system/wipe?confirmation=${encodeURIComponent(confirmation)}`, { method: "DELETE" });
    document.querySelector("#login-form").reset();
    showLogin();
    const loginMessage = document.querySelector("#login-error");
    loginMessage.textContent = "System data wiped. Create a new SUPER_ADMIN with python seed_admin.py.";
    loginMessage.style.color = "var(--accent)";
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#student-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await api("/api/admin/students", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    event.currentTarget.reset();
    showNotice("Student added.");
    refreshStudents();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#enroll-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/admin/enroll", { method: "POST", body: new FormData(event.currentTarget) });
    event.currentTarget.reset();
    showNotice("Biometric enrollment complete.");
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#camera-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await api("/api/admin/cameras", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    event.currentTarget.reset();
    showNotice("RTSP camera saved. Select it in Camera feed to connect.");
    refreshCameras();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#cameras-body").addEventListener("click", async (event) => {
  const button = event.target.closest(".remove-camera");
  if (!button || !confirm(`Remove camera ${button.dataset.id}?`)) return;
  try {
    await api(`/api/admin/cameras/${encodeURIComponent(button.dataset.id)}`, { method: "DELETE" });
    showNotice("Camera removed.");
    refreshCameras();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await api("/api/admin/users", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(values),
    });
    event.currentTarget.reset();
    showNotice("User account created.");
    refreshUsers();
  } catch (error) { showNotice(error.message, true); }
});

document.querySelector("#account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const newPassword = form.get("new_password");
  const confirmedPassword = form.get("confirm_password");
  if (newPassword !== confirmedPassword && (newPassword || confirmedPassword)) {
    showNotice("The new password and confirmation do not match.", true);
    return;
  }
  if (!form.get("username").trim() && !newPassword) {
    showNotice("Enter a new username, a new password, or both.", true);
    return;
  }
  try {
    const updated = await api("/api/admin/account", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: form.get("current_password"),
        username: form.get("username").trim() || null,
        new_password: newPassword || null,
      }),
    });
    currentUser.username = updated.username;
    document.querySelector("#account-name").textContent = updated.username;
    document.querySelector("#welcome-name").textContent = updated.username;
    event.currentTarget.reset();
    showNotice("Account updated. Other active sessions have been signed out.");
  } catch (error) { showNotice(error.message, true); }
});

api("/api/admin/me").then((user) => {
  currentUser = user;
  applyRoleAccess();
}).catch(() => showLogin());
