#ifdef HAVE_LSF_LIBRARY
#include <lsf/lsbatch.h>
#else
#define JOB_STAT_NULL 0
#define JOB_STAT_PEND 1
#define JOB_STAT_SSUSP 0x08
#define JOB_STAT_USUSP 0x10
#define JOB_STAT_PSUSP 0x02
#define JOB_STAT_RUN 0x04
#define JOB_STAT_EXIT 0x20
#define JOB_STAT_DONE 0x40
#define JOB_STAT_PDONE 0x80
#define JOB_STAT_UNKWN 0x10000
#endif
