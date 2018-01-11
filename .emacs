;; MELPA
(when (require 'package nil 'noerror)
  (setq package-archives
	'(("melpa" . "http://melpa.org/packages/")))
  (package-initialize))

;; HELM
(require 'package)
(require 'helm-config)
(helm-mode 1)
(define-key global-map [remap find-file] 'helm-find-files)
(define-key global-map [remap occur] 'helm-occur)
(define-key global-map [remap list-buffers] 'helm-buffers-list)
(define-key global-map [remap dabbrev-expand] 'helm-dabbrev)
(define-key global-map [remap execute-extended-command] 'helm-M-x)
(define-key helm-find-files-map "\t" 'helm-execute-persistent-action)
(global-set-key (kbd "C-k") 'kill-whole-line)

;; VISUALS
(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode)
  (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode)
  (scroll-bar-mode -1))
(when (fboundp 'horizontal-scroll-bar-mode)
  (horizontal-scroll-bar-mode -1))

;; THEME
(load-theme 'solarized-light t)

;; LOAD TABBAR
(add-to-list 'load-path "~/.emacs.d/tabbar/")
(load "tabbar")

;; MODES
(cua-mode t)
(tabbar-mode t)
(global-undo-tree-mode)

;; TABBAR CONFIG
(defun tabbar-buffer-groups ()
  "Return the list of group names the current buffer belongs to.
 Return a list of one element based on major mode."
  (list
   (cond
    ((or (get-buffer-process (current-buffer))
	 ;; Check if the major mode derives from `comint-mode' or
	 ;; `compilation-mode'.
	 (tabbar-buffer-mode-derived-p
	  major-mode '(comint-mode compilation-mode)))
     "Process"
     )
    ;; ((member (buffer-name)
    ;;          '("*scratch*" "*Messages*" "*Help*"))
    ;;  "Common"
    ;;  )
    ((string-equal "*" (substring (buffer-name) 0 1))
     "Common"
     )
    ((member (buffer-name)
	     '("xyz" "day" "m3" "abi" "for" "nws" "eng" "f_g" "tim" "tmp"))
     "Main"
     )
    ((eq major-mode 'dired-mode)
     "Dired"
     )
    ((memq major-mode
	   '(help-mode apropos-mode Info-mode Man-mode))
     "Common"
     )
    ((memq major-mode
	   '(rmail-mode
	     rmail-edit-mode vm-summary-mode vm-mode mail-mode
	     mh-letter-mode mh-show-mode mh-folder-mode
	     gnus-summary-mode message-mode gnus-group-mode
	     gnus-article-mode score-mode gnus-browse-killed-mode))
     "Mail"
     )
    (t
     ;; Return `mode-name' if not blank, `major-mode' otherwise.
     (if (and (stringp mode-name)
	      ;; Take care of preserving the match-data because this
	      ;; function is called when updating the header line.
	      (save-match-data (string-match "[^ ]" mode-name)))
	 mode-name
       (symbol-name major-mode))
     ))))

(defun tabbar-add-tab (tabset object &optional append_ignored)
  "Add to TABSET a tab with value OBJECT if there isn't one there yet.
 If the tab is added, it is added at the beginning of the tab list,
 unless the optional argument APPEND is non-nil, in which case it is
 added at the end."
  (let ((tabs (tabbar-tabs tabset)))
    (if (tabbar-get-tab object tabset)
	tabs
      (let ((tab (tabbar-make-tab object tabset)))
	(tabbar-set-template tabset nil)
	(set tabset (sort (cons tab tabs)
			  (lambda (a b) (string< (buffer-name (car a)) (buffer-name (car b))))))))))


(global-set-key (kbd "<C-tab>") 'tabbar-forward-tab)
(global-set-key (kbd "<C-iso-lefttab>") 'tabbar-backward-tab)

;; ???

(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(custom-safe-themes
   (quote
    ("d677ef584c6dfc0697901a44b885cc18e206f05114c8a3b7fde674fce6180879" "8db4b03b9ae654d4a57804286eb3e332725c84d7cdab38463cb6b97d5762ad26" default)))
 '(package-selected-packages
   (quote
    (markdown-mode+ markdown-mode better-defaults undo-tree solarized-theme helm color-theme-solarized))))

(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )
