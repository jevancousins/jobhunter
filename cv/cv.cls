% cv.cls - Custom CV document class based on TLCresume template
% Black and white, ATS-friendly, modular design
% Optimized for single-page CVs

\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{cv}[2025/01/27 Custom CV Class]

% Base class - 10pt for density
\LoadClass[10pt,a4paper]{article}

% Required packages
\RequirePackage[utf8]{inputenc}
\RequirePackage[T1]{fontenc}
\RequirePackage{helvet}
\renewcommand{\familydefault}{\sfdefault}

% Tighter margins for single page
\RequirePackage[top=0.4in,bottom=0.4in,left=0.5in,right=0.5in]{geometry}
\RequirePackage{titlesec}
\RequirePackage{enumitem}
\RequirePackage{hyperref}
\RequirePackage{fancyhdr}
\RequirePackage{xcolor}
\RequirePackage{etoolbox}

% Hyperlink settings (black, no boxes)
\hypersetup{
    colorlinks=true,
    linkcolor=black,
    urlcolor=black,
    pdfborder={0 0 0}
}

% Remove page numbers
\pagestyle{empty}

% Paragraph settings - minimal spacing
\setlength{\parindent}{0pt}
\setlength{\parskip}{0pt}

% Section formatting - black underline, tight spacing
\titleformat{\section}
    {\normalsize\bfseries\uppercase}
    {}
    {0pt}
    {}
    [\titlerule]

\titlespacing*{\section}{0pt}{6pt}{3pt}

% Subsection formatting (for job titles) - minimal spacing
\titleformat{\subsection}
    {\normalsize\bfseries}
    {}
    {0pt}
    {}

\titlespacing*{\subsection}{0pt}{4pt}{0pt}

% List settings - very compact bullets
\setlist[itemize]{
    leftmargin=1.2em,
    itemsep=0pt,
    parsep=0pt,
    topsep=1pt,
    partopsep=0pt
}

% ============================================
% Custom Commands
% ============================================

% Header command - Name centered, links below (compact)
\newcommand{\cvheader}[4]{%
    \begin{center}
        {\Large\bfseries #1}\\[2pt]
        {\small \href{mailto:#2}{#2} | \href{#3}{linkedin.com/in/jevancousins} | \href{#4}{github.com/jevancousins}}
    \end{center}
    \vspace{2pt}
}

% Profile/Summary command (compact)
\newcommand{\cvprofile}[1]{%
    \section{Profile}
    {\small #1}
}

% Experience entry command (compact)
% #1 = Company, #2 = Title, #3 = Dates, #4 = Location
\newcommand{\cventry}[4]{%
    \subsection{#1 \hfill \normalfont\small #3}
    \vspace{-2pt}
    {\small\textit{#2} \hfill #4}\\[-6pt]
}

% Education entry command (compact)
% #1 = Institution, #2 = Qualification, #3 = Dates, #4 = Location
\newcommand{\cveducation}[4]{%
    {\small\textbf{#1} \hfill #3\\
    #2 \hfill #4}\\[2pt]
}

% Skills category command (compact, inline)
\newcommand{\cvskillcat}[2]{%
    {\small\textbf{#1:} #2}\\[1pt]
}

% Extra/Activity entry command (compact)
% #1 = Title, #2 = Details, #3 = Dates (optional)
\newcommand{\cvextra}[3]{%
    {\small\textbf{#1} \ifx&#3&\else\hfill #3\fi\\
    #2}\\[2pt]
}

% Simple bullet for experience items
\newcommand{\cvbullet}[1]{\item {\small #1}}

% Boolean flags for section ordering
\newif\ifskillsbeforeexp
\skillsbeforeexpfalse

\newif\ifskillsafterexp
\skillsafterexpfalse

% Skill ordering commands
\newcommand{\setskillsbeforeexp}{\skillsbeforeexptrue\skillsafterexpfalse}
\newcommand{\setskillsafterexp}{\skillsbeforeexpfalse\skillsafterexptrue}
\newcommand{\setskillsafterprofile}{\skillsbeforeexpfalse\skillsafterexpfalse}

\endinput
