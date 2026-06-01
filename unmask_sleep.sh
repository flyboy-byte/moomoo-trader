#!/bin/bash
sudo systemctl unmask sleep.target suspend.target hibernate.target hybrid-sleep.target
echo "Sleep unmasked — system can suspend normally."
