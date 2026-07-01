;;; real-action-demo.el --- Human-paced real zeta! screencast driver -*- lexical-binding: t; -*-

(setq inhibit-startup-screen t
      ring-bell-function #'ignore
      make-backup-files nil
      auto-save-default nil)

(add-to-list 'load-path "/Users/remilouf/projects/zeta/emacs")
(require 'zeta-block)

(setenv "ZETA_STATE_DIR" "/private/tmp/zeta-real-emacs-action")
(setenv "ZETA_SESSION_ID" "emacs-real-action")
(setenv "ZETA_MODEL_FIRST_OUTPUT_TIMEOUT_SECONDS" "90")
(setenv "ZETA_MODEL_IDLE_TIMEOUT_SECONDS" "90")

(setq zeta-block-rpc-command
      '("/Users/remilouf/projects/zeta/.venv/bin/zeta" "rpc" "--stdio"))

(defun zeta-demo-type (text &optional delay)
  "Insert TEXT one character at a time using DELAY seconds."
  (let ((delay (or delay 0.035)))
    (dolist (char (string-to-list text))
      (insert char)
      (redisplay)
      (sit-for delay))))

(defun zeta-demo-wait-for-idle ()
  "Wait until the current Zeta queue is idle."
  (while (or zeta-block--current-task
             zeta-block--task-queue
             (buffer-live-p zeta-block--active-task-buffer)
             (> zeta-block--active-requests 0))
    (redisplay)
    (sit-for 0.5)))

(defun zeta-demo-run ()
  "Run the real zeta! demo."
  (find-file "/private/tmp/zeta-real-action-demo.md")
  (erase-buffer)
  (text-mode)
  (zeta-block-mode 1)
  (setq-local cursor-type 'bar)
  (zeta-demo-type "# Product note\n\n" 0.025)
  (zeta-demo-type
   "Zeta give product teams a way to ship agentic features without hoping the model behaves.\n\n"
   0.025)
  (sit-for 0.5)
  (zeta-demo-type "zeta! Correct typos in the previous paragraph" 0.035)
  (zeta-block-return)
  (zeta-demo-type
   "\nWhile Zeta works, I keep writing. The buffer stays live and editable.\n"
   0.025)
  (zeta-demo-wait-for-idle)
  (sit-for 4)
  (save-buffer)
  (kill-emacs 0))

(run-at-time 0.8 nil #'zeta-demo-run)
