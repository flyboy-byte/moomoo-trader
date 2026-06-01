#!/bin/bash
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
echo "Sleep masked — system will not suspend."
