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
 '(package-selected-packages
   (quote
    (centaur-tabs eshell-toggle ivy-rich pip-requirements helm-smex smex ace-mc multiple-cursors key-chord rainbow-delimiters doom-modeline docker-compose-mode straight company-lsp lsp-ui lsp-mode json-mode with-editor company-prescient ivy-prescient prescient company 2048-game ivy-historian spaceline-all-the-icons elfeed helm helm-swoop helm-rg counsel-tramp counsel-projectile all-the-icons-ivy counsel string-inflection flycheck modalka slack helm-navi navi-mode yaml-mode whitespace-cleanup-mode which-key web-mode use-package undo-tree transpose-frame swiper-helm spaceline solarized-theme ryo-modal py-isort persp-projectile neotree nav-flash nameframe-projectile nameframe-perspective markdown-mode+ keyfreq jedi ht highlight-symbol helm-tramp helm-projectile helm-flycheck helm-ag goto-last-change god-mode forge eyebrowse elpy dumb-jump dockerfile-mode docker discover dashboard csv-mode company-jedi comment-dwim-2 change-inner centered-cursor-mode boon blacken better-defaults beacon avy-zap auto-virtualenvwrapper auto-package-update auto-complete-rst all-the-icons ace-window))))
(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(default ((t (:inherit nil :stipple nil :background "#002b36" :foreground "#839496" :inverse-video nil :box nil :strike-through nil :overline nil :underline nil :slant normal :weight normal :height 106 :width normal :family "Ubuntu Mono"))))
 '(awesome-tab-selected ((t (:background "#073642" :foreground "white"))))
 '(awesome-tab-unselected ((t (:background "#073642" :foreground "grey50"))))
 '(centaur-tabs-default ((t (:background "#002B36" :foreground "#073642"))))
 '(centaur-tabs-selected ((t (:background "#073642" :foreground "#859900"))))
 '(centaur-tabs-selected-modified ((t (:background "#073642" :foreground "#859900"))))
 '(centaur-tabs-unselected ((t (:background "#073642" :foreground "#eee8d5"))))
 '(centaur-tabs-unselected-modified ((t (:background "#073642" :foreground "#eee8d5"))))
 '(tabbar-default ((t (:background "#073642" :foreground "#073642"))))
 '(tabbar-unselected ((t (:inherit tabbar-default :background "#073642" :box (:line-width 1 :color "#073642") :underline nil :slant italic)))))


(load-theme 'solarized-dark t)
