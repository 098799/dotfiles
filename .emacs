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
