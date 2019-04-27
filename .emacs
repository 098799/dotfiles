;;; .emacs --- Initialization file for Emacs

;;; Commentary:
;;; Emacs dotfile


;;; Imports:

(load "~/.emacs.conf/secrets.el" t)
(load "~/.emacs.conf/elisp.el" t)
(load "~/.emacs.conf/general.el" t)



(provide '.emacs)

(put 'downcase-region 'disabled nil)
(put 'upcase-region 'disabled nil)
(put 'narrow-to-page 'disabled nil)
(put 'narrow-to-region 'disabled nil)


;;; .emacs ends here
(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(awesome-tab-background-color "black")
 '(awesome-tab-mode t nil (awesome-tab))
 '(package-selected-packages
   (quote
    (cheat-sh ibuffer-projectile ivy-youtube ivy-pass ivy-hydra string-inflection persistent-scratch company-restclient restclient-helm linum-relative fancy-battery telephone-line all-the-icons-dired spaceline-all-the-icons pyenv-mode git-undo company-quickhelp centered-cursor-mode centered-window prettify-greek switch-buffer-functions fm-bookmarks bookmark+ dired-toggle projectile-direnv direnv curl-for-url elfeed-web elfeed-org elfeed auto-virtualenv auto-virtualenvwrapper dired dired+ dired-+ dired-imenu slack py-isort eglot company-lsp lsp-python lsp-ui lsp-mode realgud py-test python-pytest python-test pytest smartparens smartparens-config smartparents-config smart-newline smartscan visual-regexp wgrep-helm wgrep helm-tramp helm-ag ryo-modal jedi yaml-mode auto-complete-rst markdown-mode+ web-mode dockerfile-mode csv-mode virtualenvwrapper neotree forge magit elpy docker company-jedi company blacken whitespace-cleanup-mode which-key undo-tree transpose-frame swiper-helm swiper spaceline keyfreq helm-projectile helm-flycheck goto-last-change find-file-in-project dumb-jump comment-dwim-2 change-inner better-defaults avy-zap ace-window use-package solarized-theme nav-flash highlight-symbol beacon auto-package-update all-the-icons)))
 '(python-pytest-arguments (quote ("--color" "--capture=no" "--verbose" "-kMonitor")))
 '(spaceline-all-the-icons-file-name-highlight t))
(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(default ((t (:inherit nil :stipple nil :background "#002b36" :foreground "#839496" :inverse-video nil :box nil :strike-through nil :overline nil :underline nil :slant normal :weight normal :height 106 :width normal :family "Ubuntu Mono"))))
 '(awesome-tab-default ((t (:background "#002B36" :foreground "#eee8d5"))))
 '(awesome-tab-selected ((t (:background "#859900" :foreground "#eee8d5"))))
 '(awesome-tab-unselected ((t (:background "#002B36" :foreground "#eee8d5")))))
