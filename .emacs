;;; .emacs --- Initialization file for Emacs

;;; Commentary:
;;; Emacs dotfile


;;; Code:


;;;;;;;;;;;;;;
;;; CONFIG ;;;
;;;;;;;;;;;;;;

;; (when (require 'package nil 'noerror)
;;   (add-to-list
;;    'package-archives
;;    '("melpa" . "http://melpa.milkbox.net/packages/")
;;    t)
;;   (package-initialize))

(require 'package)
(setq package-enable-at-startup nil)
(setq package-archives '(("melpa" . "http://melpa.milkbox.net/packages/")
                         ("gnu" . "https://elpa.gnu.org/packages/")
                         ("marmalade" . "https://marmalade-repo.org/packages/")
                         ))
(package-initialize)

(unless (package-installed-p 'use-package)
  (package-refresh-contents)
  (package-install 'use-package))
(eval-when-compile
  (require 'use-package))

(use-package auto-package-update
   :ensure t
   :config
   (setq auto-package-update-delete-old-versions t
         auto-package-update-interval 4)
   (auto-package-update-maybe))



;;;;;;;;;;;;;;;
;;; VISUALS ;;;
;;;;;;;;;;;;;;;

(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode)
  (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode)
  (scroll-bar-mode -1))
(when (fboundp 'horizontal-scroll-bar-mode)
  (horizontal-scroll-bar-mode -1))

(use-package all-the-icons :ensure t)

(global-auto-revert-mode 1)

(use-package beacon
  :ensure t
  :config
  (beacon-mode 1)
  )

(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(default ((t (:inherit nil :stipple nil :background "#002b36" :foreground "#839496" :inverse-video nil :box nil :strike-through nil :overline nil :underline nil :slant normal :weight normal :height 130 :width normal :foundry "DAMA" :family "Ubuntu Mono")))))

(use-package highlight-symbol
  :ensure t
  :bind
  ("C-<f5>" . highlight-symbol)
  ("<f5>" . highlight-symbol-next)
  ("S-<f5>" . highlight-symbol-prev)
  ("M-<f5>" . highlight-symbol-query-replace)
  )

(use-package nav-flash
  :ensure t
  :config
  (nav-flash-show))

(load-theme 'solarized-dark t)

(add-to-list 'load-path "~/.emacs.d/tabbar/")
(load "tabbar")
(global-set-key (kbd "<C-tab>") 'tabbar-forward-tab)
(global-set-key (kbd "<C-iso-lefttab>") 'tabbar-backward-tab)


;;;;;;;;;;;;;;;
;;; GENERAL ;;;
;;;;;;;;;;;;;;;

(defun vi-open-line-below ()
  "Insert a newline below the current line and put point at beginning."
  (interactive)
  (unless (eolp)
    (end-of-line))
  (newline-and-indent))

(setq browse-url-browser-function 'browse-url-chrome)

(fset 'yes-or-no-p 'y-or-n-p)

(use-package ace-window
  :ensure t)

(use-package avy
  :ensure t)

(use-package avy-zap
  :ensure t
  :bind
  ("M-z" . avy-zap-up-to-char-dwim)
  )

(use-package better-defaults
  :ensure t)

(use-package centered-cursor-mode
  :ensure t)

(use-package change-inner
  :ensure t)

(use-package comment-dwim-2
  :ensure t
  :bind ("C-a" . comment-dwim-2))

(column-number-mode t)

(cua-mode t)

;; (use-package dashboard
;;   :ensure t
;;   :config
;;   (dashboard-setup-startup-hook))

(use-package dumb-jump
  :ensure t)

(use-package expand-region
  :ensure t
  :bind ("C-=" . er/expand-region))

(use-package find-file-in-project
  :ensure t)

(use-package git-undo
  :ensure t)

(use-package goto-last-change
  :ensure t
  )

(use-package helm-config
  :config
  (helm-mode 1)
  )

(use-package helm
  :ensure t
  :init
  (setq
   helm-M-x-fuzzy-match t
   helm-mode-fuzzy-match t
   helm-buffers-fuzzy-matching t
   helm-recentf-fuzzy-match t
   helm-locate-fuzzy-match t
   helm-semantic-fuzzy-match t
   helm-imenu-fuzzy-match t
   helm-completion-in-region-fuzzy-match t
  )
  :config
  (helm-mode 1)
  (helm-adaptive-mode t)
  :bind
  ("C-c C-p C-s C-g" . helm-do-ag-project-root)
  ("C-c p s g" . helm-do-ag-project-root)
  ("M-x" . helm-M-x)
  ("C-x C-f" . helm-find-files)
  ("C-x C-b" . helm-mini)
  ("C-x b" . helm-mini)
  )

(use-package helm-flycheck
  :ensure t)

(use-package helm-projectile
  :ensure t)

(use-package keyfreq
  :ensure t
  :config
  (keyfreq-mode 1)
  (keyfreq-autosave-mode 1)
  )

(line-number-mode t)

(global-linum-mode t)
(add-hook 'shell-mode-hook (lambda () (linum-mode -1)))

(setq org-support-shift-select t)
;; (set-default 'truncate-lines t)
;; (setq org-latex-pdf-process
;;       '("pdflatex -interaction nonstopmode -output-directory %o %f"
;;         "bibtex %b"
;;         "pdflatex -interaction nonstopmode -output-directory %o %f"
;;         "pdflatex -interaction nonstopmode -output-directory %o %f"))
;; (require 'org-ref)
;; (autoload 'helm-bibtex "helm-bibtex" "" t)
;; (setq reftex-default-bibliography "/home/grining/boybi.bib")
;; (setq org-ref-bibliography-notes "~/notes.org")
;; (setq org-ref-default-bibliography reftex-default-bibliography)
;; (setq org-ref-pdf-directory "~/Documents/Mendeley Desktop")
;; (setq bibtex-completion-bibliography reftex-default-bibliography)
;; (setq bibtex-completion-library-path "~/Documents/Mendeley Desktop/")

(recentf-mode 1)
(setq-default recent-save-file "~/.emacs.d/recentf")
(global-set-key "\C-x\ \C-r" 'helm-recentf)

(use-package slack
  :commands (slack-start)
  :init
  (setq slack-buffer-emojify t) ;; if you want to enable emoji, default nil
  (setq slack-prefer-current-team t)
  :config
  (slack-register-team
   :name "red-points"
   :default t
   :client-id ""
   :client-secret ""
   :token "xoxs-"
   :subscribed-channels '(test-rename crawler)
   :full-and-display-names t)
  :bind
  ("C-c s q" . slack-start)
  ("C-c s w" . slack-select-rooms)
  ("C-c s e" . slack-im-open)
  ("C-c s a" . slack-message-add-reaction)
  )

(use-package alert
  :commands (alert)
  :init
  (setq alert-default-style 'notifier))

(use-package spaceline
  :ensure t
  :config
  (spaceline-spacemacs-theme)
  (defun spaceline-highlight-face-god-state ()
    (if (bound-and-true-p god-local-mode)
        'spaceline-evil-normal          ;'spaceline-evil-visual
      'spaceline-evil-emacs             ;'spaceline-evil-insert
      ))
  (setq spaceline-highlight-face-func #'spaceline-highlight-face-god-state)
  )

(use-package swiper
  :ensure t)
(use-package swiper-helm
  :ensure t)

(setq tramp-default-method "ssh")
(use-package helm-tramp
  :ensure t)
;; (add-hook 'helm-tramp-pre-command-hook '(lambda () (projectile-mode 0)))
;; (add-hook 'helm-tramp-quit-hook '(lambda () (projectile-mode 1)))
(eval-after-load 'tramp '(setenv "SHELL" "/bin/bash"))

(use-package transpose-frame
  :ensure t)

(use-package undo-tree
  :ensure t
  :config
  (global-undo-tree-mode))

(use-package which-key
  :ensure t
  :init
  (setq which-key-separator " ")
  (setq which-key-prefix-prefix "+")
  :config
  (which-key-mode 1))

(use-package whitespace-cleanup-mode
  :ensure t
  :config (global-whitespace-cleanup-mode))

(winner-mode 1)



;;;;;;;;;;;;;;;;;
;;; SHORTCUTS ;;;
;;;;;;;;;;;;;;;;;

(bind-keys*
 ("M-j" . left-char)  ; used to be electric-newline-and-maybe-indent
 ("M-k" . next-line)  ; used to be kill-whole-line
 ("M-l" . previous-line)  ; used to be recenter-top-bottom
 ("M-;" . right-char)
 ("C-j" . left-word)  ; was indent-new-comment-line
 ("C-k" . forward-paragraph)  ; was kill-sentence; can be done now by M-0 C-d
 ("C-l" . backward-paragraph)  ; was downcase-word
 ("C-;" . right-word) ; was comment-dwim
 ("C-," . forward-sexp)
 ("C-." . backward-sexp)
 ("C-M-j" . move-beginning-of-line)  ; was comment-indent-new-line
 ("C-M-k" . scroll-up-command)  ; was kill-sexp
 ("C-M-l" . scroll-down-command)  ; was reposition
 ("C-M-;" . move-end-of-line)
 ("C-o" . vi-open-line-below)
 ("M-o" . ace-window)
 ;; ("C-a" . comment-dwim)  ; was move-beginning-of-line
 ("C-f" . recenter-top-bottom)  ; was forward-char
 ("C-d" . kill-whole-line)  ; was some delete
 ("C-w" . backward-kill-word)  ; was kill-region
 ("C-e" . highlight-symbol-next)  ; was same as <end>
 ("C-S-e" . highlight-symbol-prev)
 ("C-M-e" . highlight-symbol)  ; was forward-sentence
)

(global-set-key (kbd "M-:") (kbd "S-<right>"))
(global-set-key (kbd "C-:") (kbd "S-M-f"))
(global-set-key (kbd "C-M-:") (kbd "S-<end>"))
(global-set-key (kbd "C-<") (kbd "S-C-,"))
(global-set-key (kbd "C->") (kbd "S-C-."))


;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;; PYTHON AND PROJECTS ;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;

(use-package blacken
  :ensure t
  )

(use-package company
  :ensure t
  :config
  (global-company-mode)
  ;; (setq company-auto-complete t)
  (setq company-idle-delay .1)
  (setq company-show-numbers t)
  (setq company-tooltip-align-annotations 't)
  (setq company-minimum-prefix-length 1)
  (setq company-selection-wrap-around t)
  (setq completion-ignore-case 0)
  ;; (company-tng-configure-default)
  )

(use-package company-jedi
  :ensure t)
(defun my/python-mode-hook ()
  (add-to-list 'company-backends 'company-jedi))
(add-hook 'python-mode-hook 'my/python-mode-hook)

(use-package docker
  :ensure t
  :bind
  ("C-c d" . docker)
  ("C-c C-d" . docker)
  )

(use-package elpy
  :ensure t
  :config
  (elpy-enable)
  (setq elpy-rpc-backend "jedi")
  )
;; (defun elpy-goto-definition-or-rgrep ()
;;   "Go to the definition of the symbol at point, if found. Otherwise, run `elpy-rgrep-symbol'."
;;     (interactive)
;;     (ring-insert find-tag-marker-ring (point-marker))
;;     (condition-case nil (elpy-goto-definition)
;;         (error (elpy-rgrep-symbol
;;                 (concat "\\(def\\|class\\)\s" (thing-at-point 'symbol) "(")))))
;; (define-key elpy-mode-map (kbd "M-.") 'elpy-goto-definition-or-rgrep)

(use-package flycheck
  :ensure t
  :init
  (global-flycheck-mode))
(eval-after-load 'flycheck
  '(define-key flycheck-mode-map (kbd "C-c C-! C-h") 'helm-flycheck))
(eval-after-load 'flycheck
  '(define-key flycheck-mode-map (kbd "C-c ! h") 'helm-flycheck))

(global-set-key [f9] 'imenu-list-minor-mode)

;; ;; isort
;; (use-package py-isort
;;   :ensure t
;;   :config
;;   (add-hook 'before-save-hook 'py-isort-before-save)
;;   (setq py-isort-options '("--lines=100 --project=crwcommon"))
;;   )

(use-package jedi
  :config
  ;; (add-hook 'python-mode-hook 'jedi:setup)
  (setq
   jedi:complete-on-dot t
   jedi:use-shortcuts t
   jedi:environment-root "jedi"
   python-environment-directory "~/.virtualenvs")
  )

(use-package magit
  :ensure t
  :bind
  ("C-x g" . magit-status)
  ("C-c m" . magit-blame)
  )
(setenv "EDITOR" "emacsclient")

(use-package forge
  :ensure t
  )

(use-package neotree
  :ensure t
  :init
  (setq neo-theme (if (display-graphic-p) 'icons 'arrow))
  (defun neotree-project-dir ()
  "Open NeoTree using the git root."
  (interactive)
  (let ((project-dir (projectile-project-root))
        (file-name (buffer-file-name)))
    (neotree-toggle)
    (if project-dir
        (if (neo-global--window-exists-p)
            (progn
              (neotree-dir project-dir)
              (neotree-find file-name)))
      (message "Could not find git project root."))))
  )
(global-set-key [f8] 'neotree-project-dir)

(use-package projectile
  :ensure t
  :init
  :config
  (projectile-mode)
  (setq projectile-completion-system 'helm)
  (helm-projectile-on)
  :bind
  ("C-c C-p C-p" . projectile-switch-project)
  ("C-c C-p C-h" . helm-projectile)
  ("C-c C-p C-f" . projectile-find-file)
  ("C-c C-p C-d" . projectile-dir)
  ("C-c C-p C-t" . projectile-toggle-between-implementation-and-test)
  ("C-c C-p C-r" . projectile-replace)
  ("C-c C-p C-e" . projectile-replace-regexp)
  ("C-c C-p C-s s" . projectile-ag)
  ("C-c C-p C-s g" . projectile-grep)
  ("C-c C-p C-s r" . projectile-ripgrep)
  ("C-c C-p C-k" . projectile-kill-buffers)
  ("C-c C-p C-S" . projectile-save-project-buffers)
  ("C-c p p" . projectile-switch-project)
  ("C-c p h" . helm-projectile)
  ("C-c p f" . projectile-find-file)
  ("C-c p d" . projectile-dir)
  ("C-c p t" . projectile-toggle-between-implementation-and-test)
  ("C-c p r" . projectile-replace)
  ("C-c p e" . projectile-replace-regexp)
  ("C-c p s s" . projectile-ag)
  ("C-c p s g" . projectile-grep)
  ("C-c p s r" . projectile-ripgrep)
  ("C-c p k" . projectile-kill-buffers)
  ("C-c p S" . projectile-save-project-buffers)
  )

(defun python-add-breakpoint ()
  "Adding a breakpoint to a python code."
  (interactive)
  (move-end-of-line 1)
  (newline-and-indent)
  (insert "import ipdb; ipdb.set_trace()")
  (highlight-lines-matching-regexp "^[ ]*import ipdb; ipdb.set_trace()"))
(define-key global-map (kbd "C-c C-w") 'python-add-breakpoint)

(use-package python-pytest
  :bind
  ("C-c a" . python-pytest-repeat)
  ("C-c C-a" . python-pytest-popup)
  )

(use-package virtualenvwrapper
  :ensure t)
(venv-initialize-interactive-shells)
(defvar python-environment-directory)
(setq python-environment-directory "~/.virtualenvs/")
(setq venv-location "~/.virtualenvs/")
(define-key global-map (kbd "C-c C-q") 'venv-workon)
(use-package auto-virtualenvwrapper
  :ensure t
  :config
  (add-hook 'python-mode-hook #'auto-virtualenvwrapper-activate)
  (add-hook 'window-configuration-change-hook #'auto-virtualenvwrapper-activate)
  (add-hook 'focus-in-hook #'auto-virtualenvwrapper-activate))


;;;;;;;;;;;;;;;;;;;;;;
;; Other Languages ;;;
;;;;;;;;;;;;;;;;;;;;;;

(use-package csv-mode
  :ensure t
  :mode "\\.csv\\'")

(use-package dockerfile-mode
  :ensure t
  :mode "\\Dockerfile\\'")

(with-eval-after-load 'flycheck
  (setq-default flycheck-disabled-checkers '(emacs-lisp-checkdoc)))

(use-package web-mode
  :ensure t
  :mode ("\\.html\\'" "\\.jinja\\'")
  :config (setq web-mode-markup-indent-offset 2
                web-mode-code-indent-offset 2)
  )

(use-package markdown-mode
  :ensure t)

(use-package markdown-mode+
  :ensure t)

(use-package auto-complete-rst
  :ensure t
  )

(use-package yaml-mode
  :ensure t
  :config
  (require 'yaml-mode)
  (add-to-list 'auto-mode-alist '("\\.yml$" . yaml-mode))
  )


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;; EXPERIMENTAL TABBAR TWEAKS ;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; https://gist.github.com/3demax/1264635#file-tabbar-tweak-el
;; Tabbar settings
(set-face-attribute
 'tabbar-default nil
 :background "#002b36"
 :foreground "#002b36"
 :underline nil
 :box nil)
(set-face-attribute
 'tabbar-unselected nil
 :background "#002b36"
 :foreground "#aaaaaa"
 :underline nil
 :box nil)
(set-face-attribute
 'tabbar-selected nil
 :background "#aaaaaa"
 :foreground "#002b36"
 :underline nil
 :box nil)
(set-face-attribute
 'tabbar-highlight nil
 :background "#aaaaaa"
 :foreground "#002b36"
 :underline nil
 :box nil)
(set-face-attribute
 'tabbar-button nil
 :underline nil
 :box nil)
(set-face-attribute
 'tabbar-separator nil
 :underline nil
 :background "#002b36em"
 :height 0.6)

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



(defun my-copy-word (arg)
  (interactive "P")
  (save-excursion
    (cua-set-mark)
    (right-word)
    (cua-copy-region arg)
    )
  )

(defun my-backward-copy-word (arg)
  (interactive "P")
  (save-excursion
    (cua-set-mark)
    (left-word)
    (cua-copy-region arg)
    )
  )

(defun copy-whole-line (arg)
  "Copy whole line"
  (interactive "P")
  (save-excursion
    (move-beginning-of-line arg)
    (cua-set-mark)
    (forward-line)
    (cua-copy-region arg)
    )
  )

(defun copy-whole-line-or-region (arg)
  "Copy line or region"
  (interactive "P")
  (save-excursion
    (if (region-active-p)
        (cua-copy-region arg)
      (copy-whole-line arg)
      )
    )
   )

(defun kill-whole-line-or-region (arg)
  "Kills line or region"
  (interactive "P")
  (if (region-active-p)
      (cua-cut-region arg)
    (kill-whole-line)
    )
  )

(defun paste-in-new-line (arg)
  "Pasting for full line edits"
  (interactive "P")
  (move-beginning-of-line arg)
  (cua-paste arg)
  )

(use-package ryo-modal
  :commands ryo-modal-mode
  :bind ("<escape>" . ryo-modal-mode)
  :config
  (add-hook 'text-mode-hook #'ryo-modal-mode)
  (add-hook 'prog-mode-hook #'ryo-modal-mode)
  (add-hook 'fundamental-mode-hook #'ryo-modal-mode)
  ;; (add-hook 'special-mode-hook #'ryo-modal-mode)
  (add-hook 'conf-unix-mode-hook #'ryo-modal-mode)
  (ryo-modal-mode)
  (ryo-modal-keys
   ;; ("," ryo-modal-repeat)
   ;; ("q" ryo-modal-mode)
   ("U" move-beginning-of-line)
   ("u" backward-char)
   ("i" next-line)
   ("o" previous-line)
   ("p" forward-char)
   ("P" move-end-of-line)
   ("j" left-word)
   ("J" move-beginning-of-line)
   ("k" forward-paragraph)
   ("l" backward-paragraph)
   (";" right-word)
   (":" move-end-of-line)
   ("m" move-beginning-of-line)
   ("," cua-scroll-up)
   ("." cua-scroll-down)
   ("/" move-end-of-line)
   )

  (ryo-modal-keys
   ("q" kill-word)
   ("Q" my-copy-word)
   ("w" backward-kill-word)
   ("W" my-backward-copy-word)
   ("e" highlight-symbol-next)
   ("E" highlight-symbol-prev)
   ("r" avy-goto-char-2)
   ("t" vi-open-line-below)
   ("a" comment-dwim-2)
   ("s" swiper)
   ("d" kill-whole-line-or-region)
   ("D" copy-whole-line-or-region)
   ("f" recenter-top-bottom)
   ("g" keyboard-quit)
   ("h" back-to-indentation)
   ("z" undo-tree-undo)
   ("c" copy-whole-line-or-region)
   ("v" cua-paste)
   ("V" paste-in-new-line)
   ("!" helm-flycheck)
   ("-" mark-paragraph)
   ("=" er/expand-region)
   ("+" delete-horizontal-space)
   ("SPC" cua-set-mark)
   ("<" beginning-of-buffer)
   (">" end-of-buffer)
   )

  (ryo-modal-keys
   (:norepeat t)
   ("0" "M-0")
   ("1" "M-1")
   ("2" "M-2")
   ("3" "M-3")
   ("4" "M-4")
   ("5" "M-5")
   ("6" "M-6")
   ("7" "M-7")
   ("8" "M-8")
   ("9" "M-9")
   )

  (ryo-modal-key
   "["'(
        ("s" helm-projectile-ag)
        ("g" helm-projectile-grep)
        ("R" projectile-ripgrep)
        ("p" helm-projectile-switch-project)
        ("h" helm-projectile)
        ("S" projectile-save-project-buffers)
        ("d" projectile-dir)
        ("e" projectile-replace-regexp)
        ("f" projectile-find-file)
        ("k" projectile-kill-buffers)
        ("r" projectile-replace)
        ("t" projectile-toggle-between-implementation-and-test)
         )
   )

  (ryo-modal-key
   "x" '(
         ("q" venv-workon)
         ("w" python-add-breakpoint)
         ("e" eval-last-sexp)
         ("r" helm-recentf)
         ("t" elpy-multiedit-python-symbol-at-point)
         ("u" undo-tree-visualize)
         ("i" change-inner)
         ("o" change-outer)
         ("a" goto-last-change)
         ("s" save-buffer)
         ("d" dired)
         ("f" helm-find-files)
         ("g" magit-status)
         ("h" mark-whole-buffer)
         ("k" kill-buffer)
         ("x" helm-M-x)
         ("b" helm-mini)
         ("n" magit-blame)
         ("C-u" upcase-region)
         ("C-l" downcase-region)
         ("0" delete-window)
         ("1" delete-other-windows)
         ("2" split-window-below)
         ("3" split-window-right)
         ("5 0" delete-frame)
         ("5 1" delete-other-frames)
         ("5 2" make-frame-command)
         ("SPC" rectangle-mark-mode)
         ("/" dumb-jump-go)
         ("?" dumb-jump-back)
         ("." xref-find-definitions)
         ("," xref-pop-marker-stack)
         )
   )
  )


(provide '.emacs)

(put 'downcase-region 'disabled nil)
(put 'upcase-region 'disabled nil)
(put 'narrow-to-page 'disabled nil)
(put 'narrow-to-region 'disabled nil)


;;; .emacs ends here
