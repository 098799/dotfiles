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
(setq helm-M-x-fuzzy-match t)
(define-key helm-find-files-map "\t" 'helm-execute-persistent-action)
(global-set-key (kbd "C-x b") 'helm-mini)
(setq helm-buffers-fuzzy-matching t
      helm-recentf-fuzzy-match    t)

;; VISUALS
(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode)
  (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode)
  (scroll-bar-mode -1))
(when (fboundp 'horizontal-scroll-bar-mode)
  (horizontal-scroll-bar-mode -1))

;; THEME
(load-theme 'solarized-dark t)

;; ;; RECENTF
(recentf-mode 1)
(setq-default recent-save-file "~/.emacs.d/recentf") 
;; (setq recentf-max-menu-items 25)
(global-set-key "\C-x\ \C-r" 'helm-recentf) ;;  much better!!!
;; (run-at-time nil (* 5 60) 'recentf-save-list)

;; MODES
(cua-mode t)
(global-linum-mode t)
(add-hook 'shell-mode-hook (lambda () (linum-mode -1)))
(global-undo-tree-mode)
(column-number-mode t)
(line-number-mode t)
;; (global-column-enforce-mode t)
(setq column-enforce-comments nil)
(require 'better-defaults)
(sml/setup)

;; VENV stuff
(require 'virtualenvwrapper)
(venv-initialize-interactive-shells)
(setq python-environment-directory "/home/tgrining/.virtualenvs/")
(setq venv-location "/home/tgrining/.virtualenvs/")

;; PROJECTILE & HELM PROJECTILE
(projectile-global-mode)
(setq projectile-completion-system 'helm)
(helm-projectile-on)

;; JEDI
(require 'auto-complete)
(global-auto-complete-mode t)
(add-hook 'python-mode-hook 'jedi:setup)
(setq jedi:complete-on-dot t)
(setq python-environment-directory "~/.virtualenvs")

;; DEBUGGING
(defun python-add-breakpoint ()
  (interactive)
  (newline-and-indent)
  (insert "import ipdb; ipdb.set_trace()")
  (highlight-lines-matching-regexp "^[ ]*import ipdb; ipdb.set_trace()"))
 
(define-key global-map (kbd "C-c C-w") 'python-add-breakpoint)

;; CUSTOM KEYBINDING
(global-set-key (kbd "C-k") 'kill-whole-line)
(global-set-key (kbd "C-c p s g") 'helm-do-ag-project-root)


;; LOAD TABBAR
(add-to-list 'load-path "~/.emacs.d/tabbar/")
(load "tabbar")
(global-set-key (kbd "<C-tab>") 'tabbar-forward-tab)
(global-set-key (kbd "<C-iso-lefttab>") 'tabbar-backward-tab)

;; EXPERIMENTAL TABBAR TWEAKS
;; https://gist.github.com/3demax/1264635#file-tabbar-tweak-el

;; Tabbar
(require 'tabbar)
;; Tabbar settings
(set-face-attribute
 'tabbar-default nil
 :background "gray20"
 :foreground "gray20"
 :underline nil
 :box '(:line-width 1 :color "gray20" :style nil))
(set-face-attribute
 'tabbar-unselected nil
 :background "gray30"
 :foreground "white"
 :underline nil
 :box '(:line-width 1 :color "gray30" :style nil))
(set-face-attribute
 'tabbar-selected nil
 :background "gray75"
 :foreground "black"
 :underline nil
 :box '(:line-width 1 :color "gray75" :style nil))
(set-face-attribute
 'tabbar-highlight nil
 :background "white"
 :foreground "black"
 :underline nil
 :box '(:line-width 1 :color "white" :style nil))
(set-face-attribute
 'tabbar-button nil
 :underline nil
 :box '(:line-width 1 :color "gray20" :style nil))
(set-face-attribute
 'tabbar-separator nil
 :underline nil
 :background "gray20"
 :height 0.6)

;; Change padding of the tabs
;; we also need to set separator to avoid overlapping tabs by highlighted tabs
(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(compilation-message-face (quote default))
 '(cua-global-mark-cursor-color "#2aa198")
 '(cua-normal-cursor-color "#657b83")
 '(cua-overwrite-cursor-color "#b58900")
 '(cua-read-only-cursor-color "#859900")
 '(custom-safe-themes
   (quote
    ("84d2f9eeb3f82d619ca4bfffe5f157282f4779732f48a5ac1484d94d5ff5b279" "b9e9ba5aeedcc5ba8be99f1cc9301f6679912910ff92fdf7980929c2fc83ab4d" "a8245b7cc985a0610d71f9852e9f2767ad1b852c2bdea6f4aadc12cce9c4d6d0" "a24c5b3c12d147da6cef80938dca1223b7c7f70f2f382b26308eba014dc4833a" "c74e83f8aa4c78a121b52146eadb792c9facc5b1f02c917e3dbb454fca931223" "3c83b3676d796422704082049fc38b6966bcad960f896669dfc21a7a37a748fa" "8aebf25556399b58091e533e455dd50a6a9cba958cc4ebb0aab175863c25b9a4" "d677ef584c6dfc0697901a44b885cc18e206f05114c8a3b7fde674fce6180879" "8db4b03b9ae654d4a57804286eb3e332725c84d7cdab38463cb6b97d5762ad26" default)))
 '(elpy-test-pytest-runner-command (quote ("pytest")))
 '(fci-rule-color "#eee8d5")
 '(highlight-changes-colors (quote ("#d33682" "#6c71c4")))
 '(highlight-symbol-colors
   (--map
    (solarized-color-blend it "#fdf6e3" 0.25)
    (quote
     ("#b58900" "#2aa198" "#dc322f" "#6c71c4" "#859900" "#cb4b16" "#268bd2"))))
 '(highlight-symbol-foreground-color "#586e75")
 '(highlight-tail-colors
   (quote
    (("#eee8d5" . 0)
     ("#B4C342" . 20)
     ("#69CABF" . 30)
     ("#69B7F0" . 50)
     ("#DEB542" . 60)
     ("#F2804F" . 70)
     ("#F771AC" . 85)
     ("#eee8d5" . 100))))
 '(hl-bg-colors
   (quote
    ("#DEB542" "#F2804F" "#FF6E64" "#F771AC" "#9EA0E5" "#69B7F0" "#69CABF" "#B4C342")))
 '(hl-fg-colors
   (quote
    ("#fdf6e3" "#fdf6e3" "#fdf6e3" "#fdf6e3" "#fdf6e3" "#fdf6e3" "#fdf6e3" "#fdf6e3")))
 '(magit-diff-use-overlays nil)
 '(nrepl-message-colors
   (quote
    ("#dc322f" "#cb4b16" "#b58900" "#546E00" "#B4C342" "#00629D" "#2aa198" "#d33682" "#6c71c4")))
 '(package-selected-packages
   (quote
    (column-enforce-mode column-marker markdown-mode+ markdown-mode better-defaults undo-tree solarized-theme helm color-theme-solarized)))
 '(pos-tip-background-color "#eee8d5")
 '(pos-tip-foreground-color "#586e75")
 '(smartrep-mode-line-active-bg (solarized-color-blend "#859900" "#eee8d5" 0.2))
 '(sml/mode-width
   (if
       (eq
        (powerline-current-separator)
        (quote arrow))
       (quote right)
     (quote full)))
 '(sml/pos-id-separator
   (quote
    (""
     (:propertize " " face powerline-active1)
     (:eval
      (propertize " "
                  (quote display)
                  (funcall
                   (intern
                    (format "powerline-%s-%s"
                            (powerline-current-separator)
                            (car powerline-default-separator-dir)))
                   (quote powerline-active1)
                   (quote powerline-active2))))
     (:propertize " " face powerline-active2))))
 '(sml/pos-minor-modes-separator
   (quote
    (""
     (:propertize " " face powerline-active1)
     (:eval
      (propertize " "
                  (quote display)
                  (funcall
                   (intern
                    (format "powerline-%s-%s"
                            (powerline-current-separator)
                            (cdr powerline-default-separator-dir)))
                   (quote powerline-active1)
                   (quote sml/global))))
     (:propertize " " face sml/global))))
 '(sml/pre-id-separator
   (quote
    (""
     (:propertize " " face sml/global)
     (:eval
      (propertize " "
                  (quote display)
                  (funcall
                   (intern
                    (format "powerline-%s-%s"
                            (powerline-current-separator)
                            (car powerline-default-separator-dir)))
                   (quote sml/global)
                   (quote powerline-active1))))
     (:propertize " " face powerline-active1))))
 '(sml/pre-minor-modes-separator
   (quote
    (""
     (:propertize " " face powerline-active2)
     (:eval
      (propertize " "
                  (quote display)
                  (funcall
                   (intern
                    (format "powerline-%s-%s"
                            (powerline-current-separator)
                            (cdr powerline-default-separator-dir)))
                   (quote powerline-active2)
                   (quote powerline-active1))))
     (:propertize " " face powerline-active1))))
 '(sml/pre-modes-separator (propertize " " (quote face) (quote sml/modes)))
 '(tabbar-separator (quote (0.2)))
 '(term-default-bg-color "#fdf6e3")
 '(term-default-fg-color "#657b83")
 '(vc-annotate-background nil)
 '(vc-annotate-background-mode nil)
 '(vc-annotate-color-map
   (quote
    ((20 . "#dc322f")
     (40 . "#ff7f00")
     (60 . "#ffbf00")
     (80 . "#b58900")
     (100 . "#ffff00")
     (120 . "#ffff00")
     (140 . "#ffff00")
     (160 . "#ffff00")
     (180 . "#859900")
     (200 . "#aaff55")
     (220 . "#7fff7f")
     (240 . "#55ffaa")
     (260 . "#2affd4")
     (280 . "#2aa198")
     (300 . "#00ffff")
     (320 . "#00ffff")
     (340 . "#00ffff")
     (360 . "#268bd2"))))
 '(vc-annotate-very-old-color nil)
 '(weechat-color-list
   (quote
    (unspecified "#fdf6e3" "#eee8d5" "#990A1B" "#dc322f" "#546E00" "#859900" "#7B6000" "#b58900" "#00629D" "#268bd2" "#93115C" "#d33682" "#00736F" "#2aa198" "#657b83" "#839496")))
 '(xterm-color-names
   ["#eee8d5" "#dc322f" "#859900" "#b58900" "#268bd2" "#d33682" "#2aa198" "#073642"])
 '(xterm-color-names-bright
   ["#fdf6e3" "#cb4b16" "#93a1a1" "#839496" "#657b83" "#6c71c4" "#586e75" "#002b36"]))
;; adding spaces
(defun tabbar-buffer-tab-label (tab)
  "Return a label for TAB.
That is, a string used to represent it on the tab bar."
  (let ((label  (if tabbar--buffer-show-groups
                    (format "[%s]  " (tabbar-tab-tabset tab))
                  (format "%s  " (tabbar-tab-value tab)))))
    ;; Unless the tab bar auto scrolls to keep the selected tab
    ;; visible, shorten the tab label to keep as many tabs as possible
    ;; in the visible area of the tab bar.
    (if tabbar-auto-scroll-flag
        label
      (tabbar-shorten
       label (max 1 (/ (window-width)
                       (length (tabbar-view
                                (tabbar-current-tabset)))))))))

(tabbar-mode 1)

;; ;; TABBAR CONFIG
;; (defun tabbar-buffer-groups ()
;;   "Return the list of group names the current buffer belongs to.
;;  Return a list of one element based on major mode."
;;   (list
;;    (cond
;;     ((or (get-buffer-process (current-buffer))
;; 	 ;; Check if the major mode derives from `comint-mode' or
;; 	 ;; `compilation-mode'.
;; 	 (tabbar-buffer-mode-derived-p
;; 	  major-mode '(comint-mode compilation-mode)))
;;      "Process"
;;      )
;;     ;; ((member (buffer-name)
;;     ;;          '("*scratch*" "*Messages*" "*Help*"))
;;     ;;  "Common"
;;     ;;  )
;;     ((string-equal "*" (substring (buffer-name) 0 1))
;;      "Common"
;;      )
;;     ((member (buffer-name)
;; 	     '("xyz" "day" "m3" "abi" "for" "nws" "eng" "f_g" "tim" "tmp"))
;;      "Main"
;;      )
;;     ((eq major-mode 'dired-mode)
;;      "Dired"
;;      )
;;     ((memq major-mode
;; 	   '(help-mode apropos-mode Info-mode Man-mode))
;;      "Common"
;;      )
;;     ((memq major-mode
;; 	   '(rmail-mode
;; 	     rmail-edit-mode vm-summary-mode vm-mode mail-mode
;; 	     mh-letter-mode mh-show-mode mh-folder-mode
;; 	     gnus-summary-mode message-mode gnus-group-mode
;; 	     gnus-article-mode score-mode gnus-browse-killed-mode))
;;      "Mail"
;;      )
;;     (t
;;      ;; Return `mode-name' if not blank, `major-mode' otherwise.
;;      (if (and (stringp mode-name)
;; 	      ;; Take care of preserving the match-data because this
;; 	      ;; function is called when updating the header line.
;; 	      (save-match-data (string-match "[^ ]" mode-name)))
;; 	 mode-name
;;        (symbol-name major-mode))
;;      ))))
;; (defun tabbar-add-tab (tabset object &optional append_ignored)
;;   "Add to TABSET a tab with value OBJECT if there isn't one there yet.
;;  If the tab is added, it is added at the beginning of the tab list,
;;  unless the optional argument APPEND is non-nil, in which case it is
;;  added at the end."
;;   (let ((tabs (tabbar-tabs tabset)))
;;     (if (tabbar-get-tab object tabset)
;; 	tabs
;;       (let ((tab (tabbar-make-tab object tabset)))
;; 	(tabbar-set-template tabset nil)
;; 	(set tabset (sort (cons tab tabs)
;; 			  (lambda (a b) (string< (buffer-name (car a)) (buffer-name (car b))))))))))

;; ???



(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(default ((t (:inherit nil :stipple nil :background "#002b36" :foreground "#839496" :inverse-video nil :box nil :strike-through nil :overline nil :underline nil :slant normal :weight normal :height 110 :width normal :foundry "DAMA" :family "Ubuntu Mono")))))
