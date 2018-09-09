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

;; melpa
(require 'package)
(setq package-enable-at-startup nil)
(setq package-archives '(("gnu" . "https://elpa.gnu.org/packages/")
                         ("marmalade" . "https://marmalade-repo.org/packages/")
                         ("melpa" . "https://melpa.org/packages/")))
(package-initialize)

;; use-package
(unless (package-installed-p 'use-package)
  (package-refresh-contents)
  (package-install 'use-package))
(require 'use-package)


;;;;;;;;;;;;;;;
;;; VISUALS ;;;
;;;;;;;;;;;;;;;

;; bars
(menu-bar-mode -1)
(when (fboundp 'tool-bar-mode)
  (tool-bar-mode -1))
(when (fboundp 'scroll-bar-mode)
  (scroll-bar-mode -1))
(when (fboundp 'horizontal-scroll-bar-mode)
  (horizontal-scroll-bar-mode -1))

;; all-the-icons
(use-package all-the-icons :ensure t)

;; auto-revert
(global-auto-revert-mode 1)

;; beacon
(use-package beacon
  :ensure t
  :config
  (beacon-mode 1)
  )

;; fonts
(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(default ((t (:inherit nil :stipple nil :background "#002b36" :foreground "#839496" :inverse-video nil :box nil :strike-through nil :overline nil :underline nil :slant normal :weight normal :height 102 :width normal :family "Ubuntu Mono")))))

;; highlight
(require 'highlight-symbol)
(global-set-key [(control f5)] 'highlight-symbol)
(global-set-key [f5] 'highlight-symbol-next)
(global-set-key [(shift f5)] 'highlight-symbol-prev)
(global-set-key [(meta f5)] 'highlight-symbol-query-replace)
(global-set-key [(super f5)] 'highlight-symbol-remove-all)

;; nav-flash
(nav-flash-show)

;; theme
(load-theme 'solarized-dark t)

;; tabbar
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

;; better-defaults
(require 'better-defaults)

;; comment-dwim-2
(use-package comment-dwim-2
  :ensure t
  :bind ("C-a" . comment-dwim-2))

;; column-number
(column-number-mode t)

;; cua
(cua-mode t)

;; dashboard
(require 'dashboard)
(dashboard-setup-startup-hook)

;; expand-region
(use-package expand-region
  :ensure t
  :bind ("C-=" . er/expand-region))

;; find-file-in-project
(require 'find-file-in-project)

;; helm
(use-package helm-config)

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
  ("C-c p s g" . helm-do-ag-project-root)
  ("C-c p s g" . helm-do-ag-project-root)
  ("M-x" . helm-M-x)
  ("C-x C-f" . helm-find-files)
  ("C-x b" . helm-mini)
  )

;; line-number
(line-number-mode t)

;; linum
(global-linum-mode t)
(add-hook 'shell-mode-hook (lambda () (linum-mode -1)))

;; org-mode
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

;; recentf
(recentf-mode 1)
(setq-default recent-save-file "~/.emacs.d/recentf")
(global-set-key "\C-x\ \C-r" 'helm-recentf)

;; spaceline
(require 'spaceline-config)
(spaceline-spacemacs-theme)

;; undo-tree
(global-undo-tree-mode)

;; which-key
(use-package which-key
  :ensure t
  :init
  (setq which-key-separator " ")
  (setq which-key-prefix-prefix "+")
  :config
  (which-key-mode 1))

;; whitespace-cleanup-mode
(use-package whitespace-cleanup-mode
  :ensure t
  :config (global-whitespace-cleanup-mode))

;; winner-mode
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
 ("C-M-j" . move-beginning-of-line)  ; was comment-indent-new-line
 ("C-M-k" . scroll-up-command)  ; was kill-sexp
 ("C-M-l" . scroll-down-command)  ; was reposition
 ("C-M-;" . move-end-of-line)
 ("C-o" . vi-open-line-below)
 ("M-o" . ace-window)
 ;; ("C-a" . comment-dwim)  ; was move-beginning-of-line
 ("C-f" . recenter-top-bottom)  ; was forward-char
 ("C-d" . kill-whole-line)  ; was some delete
 ("C-e" . highlight-symbol-next)  ; was same as <end>
 ("C-S-e" . highlight-symbol-prev)
 ("C-M-e" . highlight-symbol)  ; was forward-sentence
)

(global-set-key (kbd "M-:") (kbd "S-<right>"))
(global-set-key (kbd "C-:") (kbd "S-M-f"))
(global-set-key (kbd "C-M-:") (kbd "S-<end>"))


;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;; PYTHON AND PROJECTS ;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;

;; ;; auto-complete
;; (require 'auto-complete)
;; (global-auto-complete-mode t)

(use-package company
  :ensure t
  :config (global-company-mode))

;; elpy
(use-package elpy
  :ensure t
  :init (elpy-enable))
;; (setq elpy-rpc-backend "jedi")
(setq python-shell-interpreter "ipython"
      python-shell-interpreter-args "-i --simple-prompt")

;; flycheck
(use-package flycheck
  :ensure t
  :init
  (global-flycheck-mode))
(eval-after-load 'flycheck
  '(define-key flycheck-mode-map (kbd "C-c ! h") 'helm-flycheck))

;; imenu
(global-set-key [f9] 'imenu-list-minor-mode)

;; jedi
;; (add-hook 'python-mode-hook 'jedi:setup)
;; (defvar jedi:complete-on-dot)
;; (setq jedi:complete-on-dot t)

;; magit
(use-package magit
  :ensure t
  :bind
  ("C-x g" . magit-status)
  ("C-c m" . magit-blame)
  :config (magit-add-section-hook 'magit-status-sections-hook
                                'magit-insert-unpushed-to-upstream
                                'magit-insert-unpushed-to-upstream-or-recent
                                'replace))

;; neotree projectile
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

;; projectile
(use-package projectile
  :ensure t
  :init
  :config
  (projectile-mode)
  (setq projectile-completion-system 'helm)
  (helm-projectile-on)
)

;; python debugging
(defun python-add-breakpoint ()
  "Adding a breakpoint to a python code."
  (interactive)
  (move-end-of-line 1)
  (newline-and-indent)
  (insert "import ipdb; ipdb.set_trace()")
  (highlight-lines-matching-regexp "^[ ]*import ipdb; ipdb.set_trace()"))
(define-key global-map (kbd "C-c C-w") 'python-add-breakpoint)

;; python pytest
(use-package python-pytest)

;; virtualevn + wrapper
(use-package virtualenvwrapper
  :ensure t)
(venv-initialize-interactive-shells)
(defvar python-environment-directory)
(setq python-environment-directory "~/.virtualenvs/")
(setq venv-location "~/.virtualenvs/")
(define-key global-map (kbd "C-c C-q") 'venv-workon)


;;;;;;;;;;;;;;;;;;;;;;
;; Other Languages ;;;
;;;;;;;;;;;;;;;;;;;;;;

;; CSV
(use-package csv-mode
  :ensure t
  :mode "\\.csv\\'")

;; Dockerfile
(use-package dockerfile-mode
  :ensure t
  :mode "\\Dockerfile\\'")

;; Elisp
(with-eval-after-load 'flycheck
  (setq-default flycheck-disabled-checkers '(emacs-lisp-checkdoc)))

;; HTML
(use-package web-mode
  :ensure t
  :mode ("\\.html\\'" "\\.jinja\\'")
  :config (setq web-mode-markup-indent-offset 2
                web-mode-code-indent-offset 2)
  )

;; Markdown
(use-package markdown-mode
  :ensure t)

(use-package markdown-mode+
  :ensure t)

;; yaml
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

(tabbar-mode 1)

(provide '.emacs)
;;; .emacs ends here
